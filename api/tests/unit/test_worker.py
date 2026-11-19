"""The Celery app's settings (M3, ADR-0006)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from regwatch.core import worker
from regwatch.core.settings import Settings


def test_the_app_is_json_only_late_acked_and_beats_the_contract_tasks(
    valid_env: dict[str, str],
) -> None:
    app = worker.make_app(Settings())
    conf = app.conf
    assert conf.task_serializer == "json" and conf.accept_content == ["json"]  # no pickle
    assert conf.task_ignore_result is True and conf.result_backend is None
    assert conf.task_acks_late
    assert conf.worker_prefetch_multiplier == 1
    assert set(conf.beat_schedule) == {
        "capture.schedule_tick",
        "capture.health_check",
        "search.reindex",
    }
    assert conf.beat_schedule["capture.schedule_tick"]["schedule"] == 60.0
    assert app.conf.broker_url.startswith("redis://")


@pytest.mark.parametrize(
    ("given", "expected"),
    [("valkey://valkey:6379/0", "redis://valkey:6379/0"),
     ("redis://valkey:6379/1", "redis://valkey:6379/1")],
)  # fmt: skip
def test_the_broker_url_speaks_redis(valid_env: dict[str, str], given: str,
                                     expected: str) -> None:  # fmt: skip
    settings = Settings().model_copy(update={"queue_url": SecretStr(given)})
    assert worker.broker_url(settings) == expected


def test_the_registered_task_names_match_the_contract(valid_env: dict[str, str]) -> None:
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[3]
    contract = yaml.safe_load((root / "docs" / "contracts" / "registries.yaml").read_text())
    app = worker.make_app(Settings())
    app.loader.import_default_modules()
    registered = {name for name in app.tasks if name.startswith("capture.")}
    expected = {n for n in contract["celery_tasks"] if n.startswith("capture.")}
    assert registered == expected - {"capture.fetch_candidate"}  # lands with the connectors
    processing = {name for name in app.tasks if name.startswith("process.")}
    # M4 runs the chain inside process.extract; the per-stage names stay unused for now
    assert processing == {"process.extract", "process.reprocess_item"}
    assert processing <= set(contract["celery_tasks"])
    searching = {name for name in app.tasks if name.startswith("search.")}
    assert searching == {"search.index_items", "search.index_matching", "search.reindex"}
    assert searching <= set(contract["celery_tasks"])


async def test_enqueue_run_sends_the_contract_task(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import uuid

    from regwatch.capture import tasks

    sent: list[tuple[str, dict[str, object]]] = []
    worker.celery_app.cache_clear()
    app = worker.celery_app()
    monkeypatch.setattr(app, "send_task", lambda name, **kw: sent.append((name, kw)))
    job = uuid.uuid4()
    await tasks.enqueue_run(job, 12.5)
    assert sent == [("capture.run_job", {"args": [str(job)], "queue": "capture",
                                         "countdown": 12.5})]  # fmt: skip
    worker.celery_app.cache_clear()


async def test_a_hanging_broker_is_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scheduler review 2: a broker that accepts and never answers cannot hold the caller."""
    import time
    import uuid

    from regwatch.capture import tasks

    monkeypatch.setattr(tasks, "_send", lambda job, countdown: time.sleep(2))
    monkeypatch.setattr(tasks, "PUBLISH_DEADLINE_S", 0.2)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        await tasks.enqueue_run(uuid.uuid4(), 0.0)
    assert time.monotonic() - started < 1.0


def test_broker_calls_are_bounded_and_remote_control_is_off(valid_env: dict[str, str]) -> None:
    """Scheduler review 1, 2, 6 and 10."""
    conf = worker.make_app(Settings()).conf
    assert conf.broker_transport_options["socket_timeout"] == worker.BROKER_TIMEOUT_S
    assert conf.broker_transport_options["socket_connect_timeout"] == worker.BROKER_TIMEOUT_S
    assert conf.task_publish_retry_policy["max_retries"] == 2
    assert conf.worker_enable_remote_control is False
    assert conf.task_reject_on_worker_lost is False  # no endless redelivery
    assert conf.beat_scheduler == "celery.beat:Scheduler"  # in memory, no pickle file


def test_tasks_have_time_and_memory_limits(valid_env: dict[str, str]) -> None:
    """RSS review finding 3: the last stop for a task that runs away."""
    import resource

    conf = worker.make_app(Settings()).conf
    assert conf.task_soft_time_limit < conf.task_time_limit == worker.TIME_LIMIT_S
    assert conf.worker_max_memory_per_child == worker.MAX_MEMORY_PER_CHILD_KB
    before = resource.getrlimit(resource.RLIMIT_AS)
    try:
        worker.limit_memory()
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        assert soft == min(worker.ADDRESS_SPACE_BYTES, hard if hard >= 0 else soft)
        assert soft <= worker.ADDRESS_SPACE_BYTES
    finally:
        resource.setrlimit(resource.RLIMIT_AS, before)

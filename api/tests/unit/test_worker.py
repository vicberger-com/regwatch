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
    assert conf.task_acks_late and conf.task_reject_on_worker_lost
    assert conf.worker_prefetch_multiplier == 1
    assert set(conf.beat_schedule) == {"capture.schedule_tick", "capture.health_check"}
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

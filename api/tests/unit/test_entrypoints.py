from __future__ import annotations

import pytest

from regwatch.api import main as api_main
from regwatch.core import entrypoints


def test_admin_requires_a_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(entrypoints.sys, "argv", ["regwatch-admin"])
    with pytest.raises(SystemExit) as exc:
        entrypoints.admin()
    assert exc.value.code == 2
    assert "create-user" in capsys.readouterr().err


def test_worker_and_beat_start_celery(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker serves the capture queue; Beat keeps its own state in /tmp (M3, ADR-0006)."""
    from regwatch.core import worker

    worker.celery_app.cache_clear()
    calls: list[tuple[str, list[str]]] = []
    app = worker.celery_app()
    monkeypatch.setattr(app, "worker_main", lambda argv: calls.append(("worker", argv)))
    monkeypatch.setattr(app, "start", lambda argv: calls.append(("start", argv)))
    entrypoints.worker()
    entrypoints.beat()
    assert calls[0][0] == "worker" and calls[0][1][:3] == ["worker", "--queues", "capture"]
    assert calls[1] == ("start", ["beat", "--loglevel", "INFO", "--schedule",
                                  entrypoints.BEAT_SCHEDULE_FILE])  # fmt: skip
    worker.celery_app.cache_clear()


def test_api_main_passes_trusted_proxies(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(api_main.uvicorn, "run", lambda *a, **kw: seen.update(kw))
    api_main.main(["--host", "127.0.0.2", "--reload"])
    assert seen["factory"] is True and seen["reload"] is True
    assert seen["forwarded_allow_ips"] == "10.89.0.2/32"


def test_api_main_fails_fast_without_settings() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        api_main.main([])

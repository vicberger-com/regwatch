from __future__ import annotations

import pytest

from regwatch.api import main as api_main
from regwatch.core import entrypoints


@pytest.mark.parametrize(("func", "issue"), [(entrypoints.seed, "#28"), (entrypoints.admin, "#31")])
def test_pending_commands_exit_with_issue(
    func: object, issue: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        func()  # type: ignore[operator]
    assert exc.value.code == 2
    assert issue in capsys.readouterr().err


@pytest.mark.parametrize("func", [entrypoints.worker, entrypoints.beat])
def test_idle_stubs_wait_for_a_signal(func: object, monkeypatch: pytest.MonkeyPatch) -> None:
    waited: list[bool] = []
    monkeypatch.setattr(entrypoints.signal, "signal", lambda *_: None)
    monkeypatch.setattr(entrypoints.signal, "pause", lambda: waited.append(True))
    func()  # type: ignore[operator]
    assert waited == [True]


def test_api_main_passes_trusted_proxies(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(api_main.uvicorn, "run", lambda *a, **kw: seen.update(kw))
    api_main.main(["--host", "127.0.0.2", "--reload"])
    assert seen["factory"] is True and seen["reload"] is True
    assert seen["forwarded_allow_ips"] == "10.0.0.0/8"


def test_api_main_fails_fast_without_settings() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        api_main.main([])

"""Secret key rotation (M10.6; env.example): a link signed with the previous key stays valid
while REGWATCH_SECRET_KEY_PREVIOUS is set, and only then."""

from __future__ import annotations

import time
import uuid

import pytest

from regwatch.core.settings import get_settings
from regwatch.outputs import services

OLD, NEW = "a" * 64, "b" * 64


def _use(monkeypatch: pytest.MonkeyPatch, key: str, previous: str | None) -> None:
    monkeypatch.setenv("REGWATCH_SECRET_KEY", key)
    if previous is None:
        monkeypatch.delenv("REGWATCH_SECRET_KEY_PREVIOUS", raising=False)
    else:
        monkeypatch.setenv("REGWATCH_SECRET_KEY_PREVIOUS", previous)
    get_settings.cache_clear()


def test_a_link_survives_a_rotation_only_in_the_window(
    valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    job, exp = uuid.uuid4(), int(time.time()) + 600
    _use(monkeypatch, OLD, None)
    sig = services.signed_link(job, "/api/v1").split("sig=")[1]
    exp = int(services.signed_link(job, "/api/v1").split("exp=")[1].split("&")[0])
    assert services.link_valid(job, exp, sig)
    _use(monkeypatch, NEW, OLD)  # rotated, with the window open
    assert services.link_valid(job, exp, sig)
    assert not services.link_valid(uuid.uuid4(), exp, sig)  # still bound to its job
    _use(monkeypatch, NEW, None)  # window closed
    assert not services.link_valid(job, exp, sig)
    get_settings.cache_clear()

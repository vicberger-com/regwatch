from __future__ import annotations

from collections.abc import Iterator

import pytest

from regwatch.core.settings import get_settings

pytest_plugins = ["tests.support.pytest_plugin"]

VALID_ENV = {
    "REGWATCH_SECRET_KEY": "a" * 64,
    "REGWATCH_DATABASE_URL": "postgresql+psycopg://regwatch:pw@127.0.0.1:1/regwatch",
    "REGWATCH_QUEUE_URL": "valkey://127.0.0.1:1/0",
    "REGWATCH_BASE_URL": "http://localhost",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Start every test from a known environment, with no REGWATCH_* leaking in."""
    import os

    for key in list(os.environ):
        if key.startswith("REGWATCH_"):
            monkeypatch.delenv(key)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def valid_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)
    return VALID_ENV

"""Integration: login, lockout, logout and sessions against PostgreSQL (#31; M1 acceptance
2, 3 and 4; REQ-14, REQ-16)."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest

from regwatch.core import seed
from regwatch.core.settings import get_settings
from regwatch.identity import admin_cli
from tests.integration.conftest import Postgres, upgrade

pytestmark = pytest.mark.integration

SEED_DIR = Path(__file__).resolve().parents[2] / "seed"
ORIGIN = {"origin": "http://localhost"}
ADMIN_PW = "admin password 1234"
VIEWER_PW = "viewer password 1234"


@pytest.fixture
def db_url(
    postgres: Postgres, empty_db: str, valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> str:
    url = postgres.url(empty_db)
    upgrade(url)
    asyncio.run(seed.run(SEED_DIR, url))
    monkeypatch.setenv("REGWATCH_DATABASE_URL", url)
    get_settings.cache_clear()
    for args, pw in (
        (["--email", "admin@example.org", "--name", "Admin"], ADMIN_PW),
        (["--email", "viewer@example.org", "--name", "Viewer", "--role", "viewer",
          "--temporary"], VIEWER_PW),
    ):  # fmt: skip
        monkeypatch.setattr("sys.stdin", io.StringIO(pw + "\n"))
        assert admin_cli.main(["create-user", *args, "--password-stdin"]) == 0
    return url


def test_admin_cli_rejects_short_password_and_duplicates(
    db_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    args = ["create-user", "--email", "x@example.org", "--name", "X", "--password-stdin"]
    assert admin_cli.main(args) == 1
    monkeypatch.setattr("sys.stdin", io.StringIO(ADMIN_PW + "\n"))
    dup = ["create-user", "--email", "admin@example.org", "--name", "A", "--password-stdin"]
    assert admin_cli.main(dup) == 1
    monkeypatch.setattr("sys.stdin", io.StringIO(ADMIN_PW + "\n"))
    assert admin_cli.main([*args[:-1], "--role", "nosuch", "--password-stdin"]) == 1
    assert "unknown roles" in capsys.readouterr().err

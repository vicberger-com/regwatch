"""Owner database credentials reach only the db and migrate containers (BL-61, re-review 6a)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = yaml.safe_load((ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8"))
OWNER_VARS = ("POSTGRES_PASSWORD", "REGWATCH_MIGRATION_DATABASE_URL")


def _env_files(service: dict[str, object]) -> list[str]:
    files = service.get("env_file", [])
    return [files] if isinstance(files, str) else list(files)  # type: ignore[arg-type]


def test_only_db_and_migrate_read_db_env() -> None:
    readers = {name for name, svc in COMPOSE["services"].items() if "db.env" in _env_files(svc)}
    assert readers == {"db", "migrate"}
    assert COMPOSE["services"]["migrate"]["profiles"] == ["tools"]
    for name, svc in COMPOSE["services"].items():
        environment = svc.get("environment", {}) or {}
        assert not set(OWNER_VARS) & set(environment), name


def test_dev_env_writes_owner_credentials_to_db_env_only(tmp_path: Path) -> None:
    for part in ("scripts/dev-env.sh", "docs/contracts/env.example"):
        (tmp_path / part).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / part, tmp_path / part)
    (tmp_path / "deploy").mkdir()
    bash = shutil.which("bash") or "/bin/bash"
    run = subprocess.run([bash, str(tmp_path / "scripts/dev-env.sh")], capture_output=True,  # noqa: S603
                         text=True, check=True, env={"PATH": os.environ["PATH"]})  # fmt: skip
    assert "deploy/db.env" in run.stdout
    app = (tmp_path / "deploy/.env").read_text()
    db = (tmp_path / "deploy/db.env").read_text()
    # The owner's password itself is in no file the app containers or the queue read, whatever
    # the variable or URL scheme it might be written under (API feed review finding 11).
    owner_password = next(line.split("=", 1)[1] for line in db.splitlines()
                          if line.startswith("POSTGRES_PASSWORD="))  # fmt: skip
    assert len(owner_password) >= 32 and owner_password not in app
    db_urls = [line for line in app.splitlines() if "postgres" in line.lower()]
    assert db_urls and all("regwatch_api:" in line for line in db_urls)
    assert not any(line.startswith(OWNER_VARS) for line in app.splitlines())
    assert all(any(line.startswith(v + "=") for line in db.splitlines()) for v in OWNER_VARS)
    assert oct((tmp_path / "deploy/db.env").stat().st_mode)[-3:] == "600"
    # BL-90 (a): the Valkey password, in queue.env for the queue and in the app's queue URL.
    queue = (tmp_path / "deploy/queue.env").read_text()
    password = next(line.split("=", 1)[1] for line in queue.splitlines()
                    if line.startswith("VALKEY_PASSWORD="))  # fmt: skip
    assert len(password) == 48 and f"valkey://regwatch:{password}@queue:6379/0" in app
    assert oct((tmp_path / "deploy/queue.env").stat().st_mode)[-3:] == "600"
    assert "VALKEY_PASSWORD" not in app and "VALKEY_PASSWORD" not in db
    assert owner_password not in queue

    # A setup from before the queue password: only queue.env and the queue URL line change.
    (tmp_path / "deploy/queue.env").unlink()
    old_app = app.replace(f"valkey://regwatch:{password}@queue", "valkey://queue")
    (tmp_path / "deploy/.env").write_text(old_app)
    upgrade = subprocess.run([bash, str(tmp_path / "scripts/dev-env.sh")], capture_output=True,  # noqa: S603
                             text=True, check=True, env={"PATH": os.environ["PATH"]})  # fmt: skip
    assert "deploy/queue.env" in upgrade.stdout
    upgraded = (tmp_path / "deploy/.env").read_text()

    def without_queue(text: str) -> list[str]:
        return [line for line in text.splitlines() if not line.startswith("REGWATCH_QUEUE_URL=")]

    assert without_queue(upgraded) == without_queue(old_app)  # secrets kept
    assert (tmp_path / "deploy/queue.env").exists() and "valkey://regwatch:" in upgraded
    app = upgraded

    (tmp_path / "deploy/db.env").unlink()  # an older setup: .env without db.env
    again = subprocess.run([bash, str(tmp_path / "scripts/dev-env.sh")], capture_output=True,  # noqa: S603
                           text=True, check=False, env={"PATH": os.environ["PATH"]})  # fmt: skip
    assert again.returncode == 1 and "BL-61" in again.stderr
    assert (tmp_path / "deploy/.env").read_text() == app  # left alone

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
    assert "regwatch_api:" in app and "regwatch:" not in app.replace("regwatch_api:", "")
    assert not any(line.startswith(OWNER_VARS) for line in app.splitlines())
    assert all(any(line.startswith(v + "=") for line in db.splitlines()) for v in OWNER_VARS)
    assert oct((tmp_path / "deploy/db.env").stat().st_mode)[-3:] == "600"

    (tmp_path / "deploy/db.env").unlink()  # an older setup: .env without db.env
    again = subprocess.run([bash, str(tmp_path / "scripts/dev-env.sh")], capture_output=True,  # noqa: S603
                           text=True, check=False, env={"PATH": os.environ["PATH"]})  # fmt: skip
    assert again.returncode == 1 and "BL-61" in again.stderr
    assert (tmp_path / "deploy/.env").read_text() == app  # left alone

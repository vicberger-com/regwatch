"""PostgreSQL 16 for migration and seed tests: one throwaway container, one database per test.

Needs a Docker daemon. The image is the digest pinned in deploy/compose.yaml. Commands run
inside the container (psql, pg_dump), so the host needs no PostgreSQL client.
"""

from __future__ import annotations

import subprocess
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

API_DIR = Path(__file__).resolve().parents[2]
PG_IMAGE = "postgres:16@sha256:5db6dac2ef5dcff512f4f00a009c3c332b9f2f28f24277175bf3e4a3d02ef83a"
PASSWORD = "it-only"  # noqa: S105 - throwaway container bound to 127.0.0.1
APP_PASSWORD = "it-app-only"  # noqa: S105 - regwatch_api, as deploy/db-init creates it


def _docker(*args: str, stdin: str | None = None) -> str:
    result = subprocess.run(  # noqa: S603
        ["docker", *args],  # noqa: S607
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


@dataclass(frozen=True)
class Postgres:
    container: str
    port: int

    def url(self, database: str) -> str:
        """The superuser, standing in for the owner login migrations use."""
        return f"postgresql://postgres:{PASSWORD}@127.0.0.1:{self.port}/{database}"

    def app_url(self, database: str) -> str:
        """``regwatch_api``, the API's least-privilege login (BL-61)."""
        return f"postgresql://regwatch_api:{APP_PASSWORD}@127.0.0.1:{self.port}/{database}"

    def psql(self, database: str, sql: str) -> str:
        return _docker(
            "exec", "-i", self.container, "psql", "-U", "postgres", "-d", database,
            "-v", "ON_ERROR_STOP=1", "-q", "-A", "-t", "-f", "-", stdin=sql,
        )  # fmt: skip

    def schema_dump(self, database: str) -> list[str]:
        """``pg_dump --schema-only`` without comments, settings or the Alembic table."""
        out = _docker(
            "exec", self.container, "pg_dump", "-U", "postgres", "--schema-only", "--no-owner",
            "--exclude-table=alembic_version", database,
        )  # fmt: skip
        skip = ("--", "SET ", "SELECT pg_catalog.set_config", "\\restrict", "\\unrestrict")
        return [line for line in out.splitlines() if line.strip() and not line.startswith(skip)]


@pytest.fixture(scope="session")
def postgres() -> Iterator[Postgres]:
    name = f"regwatch-it-{uuid.uuid4().hex[:8]}"
    _docker(
        "run", "-d", "--rm", "--name", name, "-e", f"POSTGRES_PASSWORD={PASSWORD}",
        "-p", "127.0.0.1::5432", PG_IMAGE,
    )  # fmt: skip
    try:
        port = int(_docker("port", name, "5432/tcp").splitlines()[0].rsplit(":", 1)[1])
        pg = Postgres(name, port)
        deadline = time.monotonic() + 60
        while True:  # the entrypoint restarts the server once after initdb
            try:
                pg.psql("postgres", "SELECT 1;")
                time.sleep(1)
                pg.psql("postgres", "SELECT 1;")
                break
            except RuntimeError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
        # The same roles deploy/db-init/10-api-login.sh creates in the Compose stack.
        login = f"CREATE ROLE regwatch_api LOGIN PASSWORD '{APP_PASSWORD}' IN ROLE regwatch_app;"
        pg.psql("postgres", "CREATE ROLE regwatch_app NOLOGIN;\n" + login)
        yield pg
    finally:
        _remove = ["docker", "rm", "-f", "-v", name]  # -v: drop its anonymous data volume
        subprocess.run(_remove, capture_output=True, check=False)  # noqa: S603, S607


@pytest.fixture
def empty_db(postgres: Postgres) -> str:
    """Name of a new, empty database."""
    name = f"rw_{uuid.uuid4().hex[:12]}"
    postgres.psql("postgres", f"CREATE DATABASE {name};")
    return name


def alembic_config(url: str) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logger"] = False
    return cfg


def upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str, revision: str = "base") -> None:
    command.downgrade(alembic_config(url), revision)


@pytest.fixture(autouse=True)
def processing_handovers(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A finished run hands its manifest to M4 through the broker; integration tests record the
    hand-over instead, so no test reaches a real queue."""
    from regwatch.capture import runs

    handed: list[str] = []
    monkeypatch.setattr(runs, "_to_processing", handed.append)
    return handed

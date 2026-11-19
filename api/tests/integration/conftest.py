"""PostgreSQL 16 for migration and seed tests: one throwaway container, one database per test.

Needs a Docker daemon. The image is the digest pinned in deploy/compose.yaml. Commands run
inside the container (psql, pg_dump), so the host needs no PostgreSQL client.
"""

from __future__ import annotations

import os
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
# Server settings for the load test (BL-118), e.g. "-c shared_buffers=2GB -c work_mem=32MB";
# empty for every other test run.
PG_ARGS = tuple(os.environ.get("REGWATCH_PG_ARGS", "").split())
HEAP = os.environ.get("REGWATCH_INDEX_HEAP", "512m")  # the load test sets more
INDEX_IMAGE = (
    "opensearchproject/opensearch@sha256:"
    "3bf4fe26aeb9f7b03c0ebcb1302bb24e855ee6b89fd926d26a71a83ef6f7e076"
)  # CP-22
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
        "-p", "127.0.0.1::5432", PG_IMAGE, *PG_ARGS,
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


@dataclass
class OpenSearch:
    url: str
    password: str
    ca_b64: str


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """A fixed local command (Docker, curl, the setup script); never input from a test."""
    return subprocess.run(args, env=env, capture_output=True, text=True, check=False)  # noqa: S603


@pytest.fixture(scope="session")
def opensearch(tmp_path_factory: pytest.TempPathFactory) -> Iterator[OpenSearch]:
    """A throwaway OpenSearch (ADR-0011) prepared by scripts/index-setup.sh, with its security
    plugin on, published on 127.0.0.1 only; skipped where the setup cannot run."""
    root = API_DIR.parent
    work = tmp_path_factory.mktemp("index")
    env = {**os.environ, "INDEX_SETUP_OUT": str(work / "gen"),
           "INDEX_SETUP_ENV": str(work / "index.env")}  # fmt: skip
    setup = _run([str(root / "scripts" / "index-setup.sh"), "--force"], env)
    if setup.returncode != 0:
        pytest.skip(f"index-setup.sh failed: {setup.stderr[-300:]}")
    values = dict(line.split("=", 1) for line in (work / "index.env").read_text().splitlines()
                  if "=" in line and not line.startswith("#"))  # fmt: skip
    name = f"regwatch-os-{uuid.uuid4().hex[:8]}"
    config = "/usr/share/opensearch/config"
    _docker(
        "run", "-d", "--rm", "--name", name, "--hostname", "index", "-p", "127.0.0.1::9200",
        "-e", "DISABLE_INSTALL_DEMO_CONFIG=true",
        "-e", f"OPENSEARCH_JAVA_OPTS=-Xms{HEAP} -Xmx{HEAP}",
        "--ulimit", "nofile=65536:65536",
        "-v", f"{root}/deploy/opensearch/opensearch.yml:{config}/opensearch.yml:ro",
        "-v", f"{work}/gen/certs:{config}/certs:ro",
        "-v", f"{work}/gen/security:{config}/opensearch-security:ro",
        INDEX_IMAGE,
    )  # fmt: skip
    try:
        port = int(_docker("port", name, "9200/tcp").splitlines()[0].rsplit(":", 1)[1])
        deadline = time.monotonic() + 120
        while True:  # 401: the security plugin is up and refusing anonymous calls
            probe = _run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-k",
                          f"https://127.0.0.1:{port}/"])  # fmt: skip
            if probe.stdout == "401":
                break
            if time.monotonic() > deadline:
                raise RuntimeError("OpenSearch did not start")
            time.sleep(2)
        yield OpenSearch(f"https://localhost:{port}", values["REGWATCH_INDEX_PASSWORD"],
                         values["REGWATCH_INDEX_CA_B64"])  # fmt: skip
    finally:
        _run(["docker", "rm", "-f", "-v", name])
        _run(["docker", "run", "--rm", "--user", "0", "-v", f"{work}:/w", "--entrypoint", "rm",
              INDEX_IMAGE, "-rf", "/w/gen"])  # fmt: skip

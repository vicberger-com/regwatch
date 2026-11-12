"""Integration: Schemathesis over the taxonomy operations on a seeded PostgreSQL (#34).

The DB-backed counterpart of ``tests/unit/test_contract_schemathesis.py``, with its checks.
Requests carry the pre-M1 development session, so Schemathesis also probes that requests
without it, or with a forged one, are refused.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from pydantic import SecretStr
from schemathesis.checks import not_a_server_error, positive_data_acceptance
from schemathesis.core.parameters import ParameterLocation
from sqlalchemy.ext.asyncio import async_sessionmaker

from regwatch.api.app import create_app
from regwatch.core import seed
from regwatch.core.db import create_engine
from regwatch.core.permissions import dev_session_token
from regwatch.core.settings import Settings
from tests.integration.conftest import Postgres, upgrade
from tests.unit.test_contract_schemathesis import DB_TAGS, no_unexpected_server_error

pytestmark = pytest.mark.integration
SEED_DIR = Path(__file__).resolve().parents[2] / "seed"
SETTINGS = Settings(secret_key="a" * 64, database_url="postgresql://x@127.0.0.1:1/x", env="test",
                    queue_url="valkey://127.0.0.1:1/0", base_url="http://localhost")  # fmt: skip
COOKIES = {"rw_session": dev_session_token(SETTINGS)}


@pytest.fixture(scope="module")
def taxonomy_schema(postgres: Postgres) -> Iterator[schemathesis.BaseSchema]:
    db = "rw_contract_taxonomy"
    postgres.psql("postgres", f"DROP DATABASE IF EXISTS {db}; CREATE DATABASE {db};")
    url = postgres.url(db)
    upgrade(url)
    asyncio.run(seed.run(SEED_DIR, url))
    app = create_app(SETTINGS.model_copy(update={"database_url": SecretStr(url)}))
    engine = create_engine(url, poolclass_null=True)  # each ASGI call may run on its own loop
    app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
    yield schemathesis.openapi.from_asgi("/api/v1/openapi.json", app).include(tag=DB_TAGS)


schema = schemathesis.pytest.from_fixture("taxonomy_schema")


@schema.parametrize()
@settings(max_examples=25, deadline=None, suppress_health_check=list(HealthCheck))
def test_taxonomy_api_conforms(case: schemathesis.Case) -> None:
    # A case generated without the session cookie (negative mode) must stay without it.
    drop = case.meta is not None and case.meta.is_negative_at(ParameterLocation.COOKIE)
    case.call_and_validate(
        cookies=None if drop else COOKIES,
        excluded_checks=[not_a_server_error, positive_data_acceptance],
        additional_checks=[no_unexpected_server_error],
    )

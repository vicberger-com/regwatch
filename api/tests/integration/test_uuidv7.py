"""uuidv7() from revision 0001 yields time-ordered RFC 9562 version 7 UUIDs (M0 test plan).

The function is SQL, so the test needs PostgreSQL and carries the integration marker.
"""

from __future__ import annotations

import time
import uuid

import pytest

from tests.integration.conftest import Postgres, upgrade

pytestmark = pytest.mark.integration


def test_uuidv7_values_are_time_ordered(postgres: Postgres, empty_db: str) -> None:
    upgrade(postgres.url(empty_db))
    # One value per millisecond tick: the 48-bit prefix is the Unix time in milliseconds.
    sql = "SELECT uuidv7(), pg_sleep(0.002) FROM generate_series(1, 50);"
    values = [uuid.UUID(line.split("|")[0]) for line in postgres.psql(empty_db, sql).split()]
    assert len(values) == 50
    assert values == sorted(values)
    assert len(set(values)) == 50
    now_ms = time.time() * 1000
    for value in values:
        assert value.version == 7
        assert value.variant == uuid.RFC_4122
        assert abs((value.int >> 80) - now_ms) < 60_000

"""The business gauges (M10.1b) computed from the database."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.core import metrics
from tests.integration.test_auth import db_url
from tests.integration.test_capture_runs import db

pytestmark = pytest.mark.integration
__all__ = ["db", "db_url"]


async def test_refresh_sets_every_gauge(db: AsyncSession) -> None:
    async def depths() -> dict[str, int]:
        return {"capture": 2, "process": 0, "outputs": 5}

    await metrics.refresh(db, depths)
    sample = metrics.REGISTRY.get_sample_value
    assert sample("regwatch_queue_depth", {"queue": "outputs"}) == 5
    assert sample("regwatch_outputs_failed_24h", {"kind": "print"}) == 0
    assert sample("regwatch_items_changed_1h") is not None
    assert sample("regwatch_sources_unhealthy_24h") is not None
    assert (sample("regwatch_metrics_refreshed_timestamp_seconds") or 0) > 0

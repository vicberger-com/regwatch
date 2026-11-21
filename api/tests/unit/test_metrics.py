"""Prometheus metrics (M10.1b): route templates, not raw paths; off and on loopback by default."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from regwatch.core import metrics
from regwatch.core.settings import Settings

from ..conftest import VALID_ENV


def _count(route: str, status: str) -> float:
    value = metrics.REGISTRY.get_sample_value(
        "regwatch_http_request_duration_seconds_count",
        {"method": "GET", "route": route, "status": status},
    )
    return value or 0.0


async def test_requests_are_timed_by_route_template() -> None:
    app = FastAPI()

    @app.get("/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    app.add_middleware(metrics.MetricsMiddleware)
    before, missing = _count("/items/{item_id}", "200"), _count("unmatched", "404")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        for ident in ("a", "b", "secret-search-words"):
            assert (await c.get(f"/items/{ident}")).status_code == 200
        assert (await c.get("/nowhere")).status_code == 404
    assert _count("/items/{item_id}", "200") == before + 3  # one series, whatever the id
    assert _count("unmatched", "404") == missing + 1
    exposed = [s.labels for m in metrics.REGISTRY.collect() for s in m.samples]
    assert not any("secret-search-words" in str(labels) for labels in exposed)


def test_the_listener_is_off_and_on_loopback_by_default() -> None:
    settings = Settings(**{k.removeprefix("REGWATCH_").lower(): v for k, v in VALID_ENV.items()})
    assert settings.metrics_port is None and settings.metrics_bind == "127.0.0.1"


async def test_made_up_methods_add_no_series() -> None:
    app = FastAPI()
    app.add_middleware(metrics.MetricsMiddleware)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        for n in range(5):
            await c.request(f"FOO{n}", "/x")
    methods = {s.labels.get("method") for m in metrics.REGISTRY.collect() for s in m.samples}
    assert not any(str(m).startswith("FOO") for m in methods) and "other" in methods

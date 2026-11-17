"""The dry run behind POST /sources/{id}/test (CP-13; capture/dryrun.py)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

from regwatch.capture import dryrun
from regwatch.capture.connectors.base import (
    REGISTRY,
    Candidate,
    ConnectorContext,
    ConnectorError,
    JobSettings,
)
from regwatch.capture.safe_fetch import FetchRefusedError
from regwatch.core.errors import ProblemError
from tests.unit.test_capture_execution import NOW, Fake, rows


class FakeValkey:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.ttl: dict[str, int] = {}

    async def get(self, name: str) -> bytes | None:
        value = self.data.get(name)
        return value.encode() if isinstance(value, str) else value

    async def set(self, name: str, value: str, ex: int) -> None:
        self.data[name], self.ttl[name] = value, ex

    async def delete(self, name: str) -> None:
        self.data.pop(name, None)

    async def incr(self, name: str) -> int:
        self.data[name] = int(self.data.get(name, 0)) + 1
        return int(self.data[name])

    async def expire(self, name: str, time: int) -> None:
        self.ttl[name] = time


async def make(job: JobSettings) -> ConnectorContext:
    from tests.unit.test_capture_execution import Fetcher

    async def store(key: str, body: bytes) -> None:
        raise AssertionError("the dry run must use its own store")

    return ConnectorContext(fetcher=Fetcher(), store=store, now=lambda: NOW)  # type: ignore[arg-type]


async def preview(connector: Any, monkeypatch: pytest.MonkeyPatch, **kw: Any) -> dict[str, Any]:
    if connector is None:
        monkeypatch.delitem(REGISTRY, "rss")
    else:
        monkeypatch.setitem(REGISTRY, "rss", connector)
    job, source = rows(**kw)
    return await dryrun.preview(job, source, make)


async def test_at_most_five_candidates_and_nothing_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    class Stores(Fake):
        async def discover(self, job: JobSettings,
                           ctx: ConnectorContext) -> AsyncIterator[Candidate]:  # fmt: skip
            async for c in super().discover(job, ctx):
                yield c
            await ctx.store("raw/x", b"no")  # past the fifth candidate: never reached

    got = await preview(Stores([f"https://e.org/{n}" for n in range(9)]), monkeypatch)
    assert [c["url"] for c in got["candidates"]] == [f"https://e.org/{n}" for n in range(5)]
    assert got["robots_decision"] == "allowed" and got["warnings"] == []
    assert got["candidates"][0]["published_at"] == NOW.isoformat()

    with pytest.raises(RuntimeError, match="stores nothing"):
        await dryrun._no_store("k", b"")


@pytest.mark.parametrize(
    ("error", "decision", "warning"),
    [(FetchRefusedError("robots", "robots.txt of e.org disallows it"), "disallowed", "robots"),
     (FetchRefusedError("robots", "robots.txt could not be read, so nothing"), "unreadable",
      "robots"),
     (FetchRefusedError("timeout", "server said secret"), "allowed", "timeout"),
     (ConnectorError("unsafe-feed", "the feed has a DOCTYPE"), "allowed", "unsafe-feed")],
)  # fmt: skip
async def test_refusals_become_the_decision_and_warnings(
    monkeypatch: pytest.MonkeyPatch, error: Exception, decision: str, warning: str
) -> None:
    got = await preview(Fake([], discover_error=error), monkeypatch)
    assert got["candidates"] == [] and got["robots_decision"] == decision
    assert warning in got["warnings"][0] and "secret" not in got["warnings"][0]


async def test_nothing_offered_no_connector_bad_config_and_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    assert (await preview(Fake([]), monkeypatch))["warnings"] == [
        "the source offered no candidates"
    ]
    assert "no connector" in (await preview(None, monkeypatch))["warnings"][0]
    monkeypatch.setitem(REGISTRY, "rss", Fake([]))
    bad = await preview(Fake([]), monkeypatch, config={"feed_url": "not a url"})
    assert bad["robots_decision"] == "unknown" and bad["warnings"]
    over = await preview(Fake(["https://e.org/a"]), monkeypatch, policy="override", reason="ok")
    assert over["robots_decision"] == "overridden"

    class Slow(Fake):
        async def discover(self, job: JobSettings,
                           ctx: ConnectorContext) -> AsyncIterator[Candidate]:  # fmt: skip
            await asyncio.sleep(5)
            yield Candidate(url="https://e.org/a")

    monkeypatch.setattr(dryrun, "DISCOVERY_DEADLINE_S", 0.1)
    slow = await preview(Slow([]), monkeypatch)
    assert "longer than" in slow["warnings"][0]


class Who:
    class user:  # noqa: N801 - a stand-in for Principal.user
        id = uuid.UUID(int=5)


async def test_the_request_waits_for_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    valkey = FakeValkey()
    published: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def publish(source_id: uuid.UUID, request_id: uuid.UUID) -> None:
        published.append((source_id, request_id))

    answered = {"n": 0}

    async def sleep(seconds: float) -> None:  # the worker answers after two polls
        answered["n"] += 1
        if answered["n"] == 2:
            _, rid = published[0]
            await valkey.set(dryrun.KEY.format(request_id=rid), json.dumps(
                {"candidates": [{"url": "https://e.org/a"}], "robots_decision": "allowed",
                 "warnings": []}), ex=120)  # fmt: skip

    class DB:
        async def scalar(self, query: Any) -> Any:
            return uuid.UUID(int=1)

        def add(self, row: Any) -> None:
            self.row = row

        async def commit(self) -> None:
            return None

    db = DB()
    got = await dryrun.request(db, uuid.UUID(int=1), Who(), "10.0.0.1", publish,  # type: ignore[arg-type]
                               valkey, sleep=sleep)  # fmt: skip
    assert got.candidates and got.candidates[0].url == "https://e.org/a"
    assert db.row.action == "source.test"
    assert not any(
        k.startswith("regwatch:dry-run:") and not k.startswith("regwatch:dry-run-rate:")
        for k in valkey.data
    )  # the answer is deleted once read

    async def never(seconds: float) -> None:
        return None

    monkeypatch.setattr(dryrun, "WAIT_S", 1.0)
    with pytest.raises(ProblemError) as exc:
        await dryrun.request(db, uuid.UUID(int=1), Who(), None, publish, valkey,  # type: ignore[arg-type]
                             sleep=never)  # fmt: skip
    assert exc.value.status == 504

    async def down(source_id: uuid.UUID, request_id: uuid.UUID) -> None:
        raise ConnectionError("broker down")

    with pytest.raises(ProblemError) as exc:
        await dryrun.request(db, uuid.UUID(int=1), Who(), None, down, valkey)  # type: ignore[arg-type]
    assert exc.value.status == 503

    for _ in range(dryrun.RATE_PER_MINUTE):
        await valkey.incr(dryrun.RATE_KEY.format(user_id=uuid.UUID(int=5)))
    with pytest.raises(ProblemError) as exc:
        await dryrun.request(db, uuid.UUID(int=1), Who(), None, publish, valkey)  # type: ignore[arg-type]
    assert exc.value.status == 429
    assert valkey.ttl[dryrun.RATE_KEY.format(user_id=uuid.UUID(int=5))] == 60


async def test_the_worker_answers_in_valkey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(REGISTRY, "rss", Fake(["https://e.org/a"]))
    job, source = rows()
    valkey = FakeValkey()

    class DB:
        def __init__(self, rows: list[Any]) -> None:
            self.rows = rows

        async def scalar(self, query: Any) -> Any:
            return self.rows.pop(0)

        async def rollback(self) -> None:
            return None

        def expunge(self, row: Any) -> None:
            return None

    rid = uuid.uuid4()
    await dryrun.run_on_worker(DB([source, job]), source.id, rid, make, valkey)  # type: ignore[arg-type]
    answer = json.loads(valkey.data[dryrun.KEY.format(request_id=rid)])
    assert answer["candidates"][0]["url"] == "https://e.org/a"
    assert valkey.ttl[dryrun.KEY.format(request_id=rid)] == dryrun.RESULT_TTL_S
    gone = uuid.uuid4()
    await dryrun.run_on_worker(DB([None, None]), source.id, gone, make, valkey)  # type: ignore[arg-type]
    assert "no longer exists" in valkey.data[dryrun.KEY.format(request_id=gone)]

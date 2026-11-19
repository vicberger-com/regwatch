"""The OpenSearch adapter's request building and answer checks (ADR-0011; review findings 6, 10)."""

from __future__ import annotations

from typing import Any

import pytest

from regwatch.search import indexed
from regwatch.search.index import IndexFailedError


def test_or_between_words_is_or_and_inside_a_phrase_a_word() -> None:
    got = indexed.text_query('nis2 or "terms or conditions" -draft')
    assert got is not None
    assert got["simple_query_string"]["query"] == 'nis2 | "terms or conditions" -draft'


def test_plain_words_match_any() -> None:
    got = indexed.text_query("nis2 incident")
    assert got is not None and got["multi_match"]["operator"] == "or"


def test_title_order_uses_the_folded_keyword() -> None:
    from regwatch.search.schemas import Query

    got = indexed.body(Query(sort="title_asc"), facets=False)
    assert got["sort"][0] == {"title.sort": "asc"}


class Answer:
    def __init__(self, got: Any) -> None:  # noqa: ANN401 - JSON
        self.got = got
        self.seen: dict[str, Any] = {}

    async def call(self, method: str, path: str, body: Any = None, **kw: Any) -> Any:  # noqa: ANN401
        self.seen = {"body": body, **kw}
        return self.got


@pytest.mark.parametrize("got", [
    {"hits": {"hits": [{"_id": "not-a-uuid"}]}},
    {"hits": {"hits": [{}]}},
    {"hits": []},
    ["not", "an", "object"],
])  # fmt: skip
async def test_an_unexpected_search_answer_is_an_index_failure(got: Any) -> None:  # noqa: ANN401
    from regwatch.search.schemas import Query

    with pytest.raises(IndexFailedError) as failed:
        await indexed.search(Answer(got), Query(q="x"), facets=False)  # type: ignore[arg-type]
    assert failed.value.reason == "index-answer"


async def test_an_early_stop_is_a_timeout_never_a_partial_answer() -> None:
    from regwatch.search.schemas import Query

    client = Answer({"timed_out": True, "hits": {"hits": [], "total": {"value": 0}}})
    with pytest.raises(IndexFailedError) as failed:
        await indexed.search(client, Query(q="x"), facets=True)  # type: ignore[arg-type]
    assert failed.value.reason == "index-timeout"
    assert client.seen["params"]["timeout"] == "3s"
    assert client.seen["params"]["cancel_after_time_interval"] == "3s"
    assert client.seen["deadline"] == 4.0


async def test_an_unexpected_map_answer_is_an_index_failure() -> None:
    from datetime import UTC, datetime

    bad = {"aggregations": {"events": {"period": {"places": {"buckets": [{"key": "DE"}]}}}}}
    now = datetime.now(UTC)
    with pytest.raises(IndexFailedError):
        await indexed.activity(Answer(bad), None, now, now, "country")  # type: ignore[arg-type]

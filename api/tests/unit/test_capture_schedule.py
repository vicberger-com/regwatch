"""When capture jobs run next (M3 design notes; capture/schedule.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from regwatch.capture.schedule import CronError, next_cron, next_run, parse_cron

UTC_ZONE = ZoneInfo("UTC")


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.mark.parametrize(
    ("expr", "after", "expected"),
    [
        ("*/30 * * * *", "2026-11-16T10:07:00", "2026-11-16T10:30:00"),
        ("*/30 * * * *", "2026-11-16T10:30:00", "2026-11-16T11:00:00"),  # strictly after
        ("*/30 * * * *", "2026-11-16T10:29:59.9", "2026-11-16T10:30:00"),
        ("0 9 * * MON-FRI", "2026-11-14T12:00:00", "2026-11-16T09:00:00"),  # Sat -> Mon
        ("0 0 * * 7", "2026-11-16T00:00:00", "2026-11-22T00:00:00"),  # 7 is Sunday
        ("0 0 1 JAN *", "2026-11-16T00:00:00", "2027-01-01T00:00:00"),
        ("5/15 * * * *", "2026-11-16T10:21:00", "2026-11-16T10:35:00"),
        ("0 12 29 2 *", "2026-11-16T00:00:00", "2028-02-29T12:00:00"),
        ("0 0 13 * FRI", "2026-11-16T00:00:00", "2026-11-20T00:00:00"),  # either day matches
        ("1,2-4,10-20/5 3 * * *", "2026-11-16T03:04:00", "2026-11-16T03:10:00"),
        ("59 23 31 12 *", "2026-12-31T23:59:00", "2027-12-31T23:59:00"),
    ],
)  # fmt: skip
def test_next_cron(expr: str, after: str, expected: str) -> None:
    assert next_cron(parse_cron(expr), at(after), UTC_ZONE) == at(expected)


@pytest.mark.parametrize(
    "expr",
    ["* * *", "60 * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *", "* * * * 8",
     "5-1 * * * *", "*/0 * * * *", "*/61 * * * *", "² * * * *", "*/² * * * *",
     "١ * * * *", "1-² * * * *", "* * * FOO *", "* * * * " + "1," * 200 + "1",
     "a b c d e"],
)  # fmt: skip
def test_bad_cron_is_refused(expr: str) -> None:
    with pytest.raises(CronError):
        parse_cron(expr)


def test_a_cron_that_never_fires() -> None:
    assert next_cron(parse_cron("0 0 30 2 *"), at("2026-11-16T00:00:00"), UTC_ZONE) is None


def test_time_zones_and_daylight_saving() -> None:
    vienna = ZoneInfo("Europe/Vienna")
    # 09:00 in Vienna in November (UTC+1) is 08:00 UTC.
    assert next_cron(parse_cron("0 9 * * *"), at("2026-11-16T00:00:00"), vienna) == at(
        "2026-11-16T08:00:00")  # fmt: skip
    # 2027-03-28 02:30 does not exist in Vienna (clocks go 02:00 -> 03:00): skipped that day.
    got = next_cron(parse_cron("30 2 * * *"), at("2027-03-27T02:00:00"), vienna)
    assert got == at("2027-03-29T00:30:00")
    # 2026-10-25 02:30 happens twice in Vienna: once, at the first (summer time, UTC+2).
    got = next_cron(parse_cron("30 2 * * *"), at("2026-10-24T12:00:00"), vienna)
    assert got == at("2026-10-25T00:30:00")


def test_next_run_for_each_kind_of_schedule() -> None:
    now = at("2026-11-16T10:00:00")
    assert next_run(None, 1800, "UTC", now) == now + timedelta(seconds=1800)
    assert next_run("0 * * * *", None, "UTC", now) == at("2026-11-16T11:00:00")
    assert next_run(None, None, "UTC", now) is None

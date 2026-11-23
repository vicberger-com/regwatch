"""The schedule check (M8.3): a valid cron and zone, an hour between runs all year."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from regwatch.outputs.schedules import check

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def test_the_first_run_is_in_the_schedules_zone() -> None:
    assert check("0 7 * * 1", "Europe/Berlin", NOW) == datetime(2026, 11, 23, 6, 0, tzinfo=UTC)


def test_a_clock_change_months_away_is_checked() -> None:
    """Lord Howe moves its clocks 30 minutes in October: 01:30 and 02:30 are then half an hour
    apart, ten months after ``NOW`` (M8.3 review: 50 runs did not reach it)."""
    assert check("30 1,2 * * *", "UTC", NOW)
    with pytest.raises(ValueError, match="at least an hour"):
        check("30 1,2 * * *", "Australia/Lord_Howe", NOW)


def test_an_hourly_schedule_is_allowed() -> None:
    assert check("0 * * * *", "Europe/Berlin", NOW)


def test_a_short_gap_stops_the_check_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """G5 review, Medium 1: a refused schedule is not walked for a year."""
    from regwatch.outputs import schedules

    calls = 0
    real = schedules.next_run

    def counting(*args: object) -> datetime | None:
        nonlocal calls
        calls += 1
        return real(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(schedules, "next_run", counting)
    with pytest.raises(ValueError, match="at least an hour"):
        check("*/5 * * * *", "UTC", NOW)
    assert calls == 2

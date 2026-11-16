"""When a capture job runs next (M3 design notes: Beat enqueues jobs whose ``next_run_at`` passed).

A job has a five-field cron expression or an interval of at least 15 minutes
(``capture_job``). Cron fields follow the usual rules: numbers, ``*``, ranges, lists and steps;
month and weekday names (``JAN``, ``MON``); weekday 0 or 7 is Sunday; when both day-of-month
and day-of-week are restricted, a day matching either one is a match, as cron does.

Times are computed in the job's time zone and stored in UTC. A wall-clock time skipped by a
daylight-saving change does not happen that day; a repeated one happens once, at its first
occurrence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
NAMES = {3: "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(),
         4: "SUN MON TUE WED THU FRI SAT".split()}  # fmt: skip
MAX_CRON = 200
SEARCH_DAYS = 366 * 8  # long enough for Feb 29 on a given weekday; past it, never


class CronError(ValueError):
    pass


@dataclass(frozen=True)
class Cron:
    minutes: tuple[int, ...]
    hours: tuple[int, ...]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]  # 0 is Sunday
    any_day: bool  # day-of-month was *
    any_weekday: bool  # day-of-week was *

    def day_matches(self, day: date) -> bool:
        if day.month not in self.months:
            return False
        by_day = day.day in self.days
        by_weekday = (day.isoweekday() % 7) in self.weekdays
        if self.any_day or self.any_weekday:
            return by_day and by_weekday
        return by_day or by_weekday


def _value(index: int, text: str) -> int:
    if text.isascii() and text.isdigit():
        return int(text)
    names = NAMES.get(index, [])
    if text.upper() in names:
        return names.index(text.upper()) + (1 if index == 3 else 0)
    raise CronError(f"{text!r} is not a value")


def _field(index: int, text: str) -> set[int]:
    low, high = RANGES[index]
    found: set[int] = set()
    for part in text.split(","):
        span, slash, step_text = part.partition("/")
        step = 1
        if slash:
            if not (step_text.isascii() and step_text.isdigit()) or not 1 <= int(step_text) <= high:
                raise CronError(f"{part!r} has a bad step")
            step = int(step_text)
        if span == "*":
            first, last = low, high
        else:
            start, dash, end = span.partition("-")
            first = _value(index, start)
            last = _value(index, end) if dash else (high if slash else first)
            if not (low <= first <= high and low <= last <= high) or first > last:
                raise CronError(f"{part!r} is out of range")
        found.update(range(first, last + 1, step))
    return found


def parse_cron(expr: str) -> Cron:
    fields = expr.split()
    if len(expr) > MAX_CRON or len(fields) != 5:
        raise CronError("a cron expression has five fields")
    minutes, hours, days, months, weekdays = (_field(i, f) for i, f in enumerate(fields))
    return Cron(tuple(sorted(minutes)), tuple(sorted(hours)), frozenset(days),
                frozenset(months), frozenset(w % 7 for w in weekdays),
                fields[2] == "*", fields[4] == "*")  # fmt: skip


def _exists(local: datetime, zone: ZoneInfo) -> bool:
    """False for a wall-clock time a daylight-saving change skips."""
    return local.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == local.replace(
        tzinfo=None)  # fmt: skip


def next_cron(cron: Cron, after: datetime, zone: ZoneInfo) -> datetime | None:
    """The first time strictly after ``after`` that ``cron`` names, in UTC; None if never."""
    start = after.astimezone(zone)
    floor = start.replace(second=0, microsecond=0, tzinfo=None) + timedelta(minutes=1)
    day = floor.date()
    for _ in range(SEARCH_DAYS):
        if cron.day_matches(day):
            for hour in cron.hours:
                for minute in cron.minutes:
                    wall = datetime(day.year, day.month, day.day, hour, minute)
                    if wall < floor:
                        continue
                    local = wall.replace(tzinfo=zone, fold=0)
                    if _exists(local, zone):
                        return local.astimezone(UTC)
        day += timedelta(days=1)
    return None


def next_run(cron: str | None, interval_seconds: int | None, timezone: str,
             after: datetime) -> datetime | None:  # fmt: skip
    """When a job with this schedule runs next after ``after`` (UTC)."""
    if cron is not None:
        return next_cron(parse_cron(cron), after, ZoneInfo(timezone))
    if interval_seconds is not None:
        return (after + timedelta(seconds=interval_seconds)).astimezone(UTC)
    return None

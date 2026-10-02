"""Quiet-hours time logic (KR2): window over midnight and on the same day, exact boundaries, next change."""
from datetime import datetime, time, timezone

from custom_components.aikos.quiet_hours import is_quiet, next_change

NIGHT = (time(20, 0), time(7, 0))
NOON = (time(13, 0), time(15, 0))


def test_over_midnight_boundaries():
    assert not is_quiet(time(19, 59, 59), *NIGHT)
    assert is_quiet(time(20, 0), *NIGHT)                 # start counts
    assert is_quiet(time(23, 59), *NIGHT)
    assert is_quiet(time(0, 0), *NIGHT)
    assert is_quiet(time(6, 59, 59), *NIGHT)
    assert not is_quiet(time(7, 0), *NIGHT)              # end doesn't
    assert not is_quiet(time(12, 0), *NIGHT)


def test_same_day_window():
    assert not is_quiet(time(12, 59), *NOON)
    assert is_quiet(time(13, 0), *NOON)
    assert is_quiet(time(14, 59, 59), *NOON)
    assert not is_quiet(time(15, 0), *NOON)
    assert not is_quiet(time(0, 0), *NOON)


def test_empty_window_is_never_quiet():
    assert not is_quiet(time(8, 0), time(8, 0), time(8, 0))
    assert next_change(datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), time(8, 0), time(8, 0)) is None


def test_next_change():
    tz = timezone.utc
    assert next_change(datetime(2026, 10, 2, 14, 0, tzinfo=tz), *NIGHT) == datetime(2026, 10, 2, 20, 0, tzinfo=tz)
    assert next_change(datetime(2026, 10, 2, 20, 0, tzinfo=tz), *NIGHT) == datetime(2026, 10, 3, 7, 0, tzinfo=tz)
    assert next_change(datetime(2026, 10, 2, 23, 0, tzinfo=tz), *NIGHT) == datetime(2026, 10, 3, 7, 0, tzinfo=tz)
    assert next_change(datetime(2026, 10, 3, 7, 0, tzinfo=tz), *NIGHT) == datetime(2026, 10, 3, 20, 0, tzinfo=tz)
    assert next_change(datetime(2026, 10, 2, 13, 30, tzinfo=tz), *NOON) == datetime(2026, 10, 2, 15, 0, tzinfo=tz)

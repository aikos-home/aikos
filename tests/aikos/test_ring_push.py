"""When a ring becomes a push (KR8): quiet hours, nobody home, someone home, storm ringing; the text."""
from datetime import datetime, timedelta, timezone

from custom_components.aikos.ring_push import MIN_GAP, NOBODY_HOME, QUIET_HOURS, push_message, push_reason

NOW = datetime(2026, 10, 2, 22, 14, tzinfo=timezone.utc)


def test_quiet_hours_push_even_with_everybody_home():
    assert push_reason(True, ["home", "home"], None, NOW) == QUIET_HOURS


def test_nobody_home_pushes_unknown_counts_as_away():
    assert push_reason(False, ["not_home", "unknown"], None, NOW) == NOBODY_HOME


def test_someone_home_by_day_no_push():
    assert push_reason(False, ["home", "not_home"], None, NOW) is None


def test_no_residents_configured_never_means_nobody_home():
    assert push_reason(False, [], None, NOW) is None


def test_storm_ringing_is_one_push():
    assert push_reason(True, [], NOW - timedelta(seconds=5), NOW) is None
    assert push_reason(True, [], NOW - MIN_GAP, NOW) == QUIET_HOURS


def test_message_in_the_house_language():
    assert push_message(QUIET_HOURS, NOW, "de") == "Es hat geklingelt (22:14) · Ruhezeit"
    assert push_message(NOBODY_HOME, NOW, "en-GB") == "Someone rang the doorbell (22:14) · nobody home"

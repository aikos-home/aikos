"""The door actions' rules without Home Assistant (aikos-app A11–A14, A26, A39–A41) and the RTP framing for the door."""
import struct
from datetime import datetime, time, timedelta, timezone

import pytest

from custom_components.aikos.door_rules import (
    DoorState,
    Greeting,
    Mute,
    Note,
    check_window,
    clean_note,
    mute_until,
)
from custom_components.aikos.door_speaker import FRAME, frames_of
from custom_components.aikos.ring_push import BELL_MUTED, QUIET_HOURS, push_message, push_reason

TZ = timezone(timedelta(hours=2))
NOW = datetime(2026, 10, 21, 14, 50, 0, tzinfo=TZ)


def iso(dt):
    return dt.isoformat(timespec="seconds")


def test_mute_for_minutes_and_until_the_next_time_of_day():
    assert mute_until(NOW, minutes=60) == NOW + timedelta(hours=1)
    assert mute_until(NOW, minutes=10**9) == NOW + timedelta(days=7)          # capped
    assert mute_until(NOW, until_time=time(7, 0)) == datetime(2026, 10, 22, 7, 0, tzinfo=TZ)   # "bis morgen 7:00"
    assert mute_until(NOW, until_time=time(16, 0)) == datetime(2026, 10, 21, 16, 0, tzinfo=TZ)
    with pytest.raises(ValueError):
        mute_until(NOW)


def test_mute_is_active_until_its_end_or_forever():
    assert not Mute().active(NOW)
    assert Mute(on=True).active(NOW)                                            # until switched off
    assert Mute(on=True, until=iso(NOW + timedelta(minutes=1))).active(NOW)
    assert not Mute(on=True, until=iso(NOW)).active(NOW)


def test_note_is_cleaned_and_never_empty():
    assert clean_note("  Komme\n  sofort  ", " Alex ") == ("Komme sofort", "Alex")
    assert len(clean_note("x" * 1000, "")[0]) == 400
    with pytest.raises(ValueError):
        clean_note("   ", "Alex")


def test_a_new_visit_only_after_two_minutes_without_radar():
    """The owner, 22.10.: the radar lost someone sitting in front of it for 3 s and the greeting played again."""
    from custom_components.aikos.door_rules import new_visit
    assert new_visit(None, NOW)                                                # nobody since the start
    assert not new_visit(NOW - timedelta(seconds=3), NOW)
    assert not new_visit(NOW - timedelta(seconds=119), NOW)
    assert new_visit(NOW - timedelta(minutes=2), NOW)


def test_greeting_window_and_not_during_a_call():
    g = Greeting(enabled=True, text="Hallo", audio="greeting-1.webm", start=iso(NOW - timedelta(hours=1)),
                 end=iso(NOW + timedelta(hours=1)))
    assert g.in_window(NOW) and g.may_play(NOW, in_call=False)
    assert not g.may_play(NOW, in_call=True)
    assert not g.in_window(NOW + timedelta(hours=2)) and not g.in_window(NOW - timedelta(hours=2))
    assert g.next_change(NOW) == NOW + timedelta(hours=1)
    assert not Greeting(enabled=True, text="Hallo").may_play(NOW, False)          # text only: the screen shows it, no sound
    assert not Greeting(enabled=False, text="Hallo").in_window(NOW)
    assert not Greeting(enabled=True).in_window(NOW)                             # nothing to greet with
    with pytest.raises(ValueError):
        check_window(NOW, NOW - timedelta(minutes=1))


def test_state_round_trips_and_bad_data_gives_defaults():
    s = DoorState(mute=Mute(on=True, until=iso(NOW)), note=Note("Komme", "Alex", iso(NOW)),
                  greeting=Greeting(enabled=True, text="Hallo"), picture="foto-ab.png")
    assert DoorState.from_dict(s.to_dict()) == s
    assert DoorState.from_dict(None) == DoorState()
    assert DoorState.from_dict({"mute": {"on": True, "bogus": 1}, "greeting": {"enabled": True, "x": 2}}).mute.on
    assert DoorState.from_dict({"greeting": "nonsense"}) == DoorState()


def test_a_muted_bell_still_pushes():
    assert push_reason(False, ["home"], None, NOW, muted=True) == BELL_MUTED
    assert push_reason(True, ["home"], None, NOW, muted=True) == QUIET_HOURS
    assert push_reason(False, ["home"], None, NOW) is None                      # default unchanged
    assert push_message(BELL_MUTED, NOW, "de") == "Es hat geklingelt (14:50) · Klingel stumm"


def test_rtp_frames_for_the_door():
    pcm = b"\x01\x02" * (FRAME + 10)                                            # 1 frame + a bit: padded to 2
    frames = frames_of(pcm)
    assert len(frames) == 2 and all(len(f) == 12 + FRAME * 2 for f in frames)
    v, pt, seq0, ts0, ssrc = struct.unpack("!BBHII", frames[0][:12])
    _, pt1, seq1, ts1, ssrc1 = struct.unpack("!BBHII", frames[1][:12])
    assert v == 0x80 and pt == 96 | 0x80 and pt1 == 96                          # marker on the first frame only
    assert seq1 == (seq0 + 1) & 0xFFFF and ts1 == (ts0 + FRAME) & 0xFFFFFFFF and ssrc1 == ssrc
    assert frames[1][12 + 20:] == b"\0" * (FRAME * 2 - 20)

"""The door actions in a real Home Assistant test instance: bell mute (A14/A40) with the ring push, quiet hours for the app,
a note to the door now or for the next visitor (A11/A39), the door picture (A12/A41), the greeting (A13/A26)."""
import base64
import io
import os
from datetime import datetime

import pytest
from homeassistant import config_entries
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from PIL import Image
from pytest_homeassistant_custom_component.common import async_capture_events, async_fire_time_changed, async_mock_service

DOMAIN = "aikos"
MUTED, MUTE_SWITCH = "binary_sensor.aikos_bell_muted", "switch.aikos_bell_mute"
NOTE, GREETING, PICTURE = "sensor.aikos_door_note", "sensor.aikos_door_greeting", "sensor.aikos_door_picture"
SOMEONE, CALL = "binary_sensor.aikos_intercom_screen_someone_at_the_door", "binary_sensor.aikos_intercom_talk_in_call"
GREETING_TEXT, PHOTO_URL = "text.aikos_intercom_screen_greeting", "text.aikos_intercom_screen_photo_url"
BELL = "event.test_doorbell"


def local(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=dt_util.get_default_time_zone())


@pytest.fixture
def media(hass: HomeAssistant, tmp_path):
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    hass.config.internal_url = "http://192.0.2.10:8123"
    return tmp_path / "media"


@pytest.fixture
def door(hass: HomeAssistant):
    """The door's entities and actions as the screen provides them."""
    shown = async_mock_service(hass, "esphome", "aikos_intercom_screen_show_reply")
    texts = []

    async def set_value(call):
        texts.append((call.data["entity_id"], call.data["value"]))
        hass.states.async_set(call.data["entity_id"], call.data["value"])
    hass.services.async_register("text", "set_value", set_value)
    for e, s in ((SOMEONE, "off"), (CALL, "off"), (GREETING_TEXT, ""), (PHOTO_URL, "")):
        hass.states.async_set(e, s)
    return shown, texts


async def setup(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    return hass.config_entries.async_entries(DOMAIN)[0]


async def call(hass, service, data=None, response=False, context=None):
    return await hass.services.async_call(DOMAIN, service, data or {}, blocking=True, return_response=response, context=context)


async def radar(hass, state):
    hass.states.async_set(SOMEONE, state)
    await hass.async_block_till_done()


# bell mute (A14/A40)
async def test_mute_for_an_hour_ends_by_itself(hass: HomeAssistant, media, door, freezer):
    freezer.move_to(local(21, 14, 50))
    await setup(hass)
    assert hass.states.get(MUTED).state == "off"
    await call(hass, "bell_mute", {"minutes": 60})
    st = hass.states.get(MUTED)
    assert st.state == "on" and st.attributes["until"].startswith("2026-10-21T15:50")
    assert hass.states.get(MUTE_SWITCH).state == "on"
    freezer.move_to(local(21, 15, 51))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(MUTED).state == "off" and hass.states.get(MUTE_SWITCH).state == "off"


async def test_mute_until_tomorrow_morning_and_until_switched_off(hass: HomeAssistant, media, door, freezer):
    freezer.move_to(local(21, 22, 0))
    await setup(hass)
    await call(hass, "bell_mute", {"until_time": "07:00"})
    assert hass.states.get(MUTED).attributes["until"].startswith("2026-10-22T07:00")
    await hass.services.async_call("switch", "turn_on", {"entity_id": MUTE_SWITCH}, blocking=True)
    assert hass.states.get(MUTED).state == "on" and hass.states.get(MUTED).attributes["until"] == ""
    await call(hass, "bell_unmute")
    assert hass.states.get(MUTED).state == "off"
    with pytest.raises(ServiceValidationError):
        await call(hass, "bell_mute", {})


async def test_a_ring_while_muted_still_pushes(hass: HomeAssistant, media, door, freezer):
    freezer.move_to(local(21, 14, 0))
    hass.config.language = "de"
    phone = async_mock_service(hass, "notify", "aikos_phone_a")
    hass.states.async_set(BELL, "2026-10-21T10:00:00.000+00:00")
    hass.states.async_set("person.a", "home")
    entry = await setup(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"doorbell": BELL, "residents": ["person.a"], "notify_targets": ["notify.aikos_phone_a"]})
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    hass.states.async_set(BELL, "2026-10-21T12:00:01.000+00:00")
    await hass.async_block_till_done()
    assert phone == []                                                      # by day, someone home: no push
    await call(hass, "bell_mute", {"minutes": 30})
    hass.states.async_set(BELL, "2026-10-21T12:00:40.000+00:00")
    await hass.async_block_till_done()
    assert [c.data["message"] for c in phone] == ["Es hat geklingelt (14:00) · Klingel stumm"]


async def test_quiet_hours_through_the_service(hass: HomeAssistant, media, door):
    await setup(hass)
    await call(hass, "quiet_hours", {"enabled": False, "start": "21:30", "end": "06:45"})
    assert hass.states.get("switch.aikos_quiet_hours").state == "off"
    assert hass.states.get("time.aikos_quiet_hours_start").state == "21:30:00"
    assert hass.states.get("time.aikos_quiet_hours_end").state == "06:45:00"


# a note to the door (A11/A39)
async def test_a_note_is_shown_now_if_someone_is_there(hass: HomeAssistant, media, door):
    shown, _ = door
    await setup(hass)
    replies = async_capture_events(hass, "aikos_door_reply")
    await radar(hass, "on")
    res = await call(hass, "door_say", {"message": "Komme sofort", "sender": "Alex"}, response=True)
    assert res == {"delivered": "now"} and [c.data for c in shown] == [{"sender": "Alex", "message": "Komme sofort"}]
    assert [e.data for e in replies] == [{"sender": "Alex", "text": "Komme sofort"}]
    assert hass.states.get(NOTE).state == "none"


async def test_a_note_waits_for_the_next_visitor_and_is_gone_after(hass: HomeAssistant, media, door):
    shown, _ = door
    await setup(hass)
    res = await call(hass, "door_say", {"message": "Paket bitte in die Box", "sender": "Alex"}, response=True)
    assert res == {"delivered": "waiting"} and shown == []
    st = hass.states.get(NOTE)
    assert st.state == "waiting" and st.attributes["message"] == "Paket bitte in die Box"
    await radar(hass, "on")
    assert [c.data["message"] for c in shown] == ["Paket bitte in die Box"] and hass.states.get(NOTE).state == "none"
    await radar(hass, "off")
    await radar(hass, "on")
    assert len(shown) == 1                                                  # only once


async def test_a_waiting_note_can_be_withdrawn(hass: HomeAssistant, media, door):
    shown, _ = door
    await setup(hass)
    await call(hass, "door_say", {"message": "Bin gleich da"})
    assert await call(hass, "door_say_cancel", response=True) == {"cancelled": True}
    await radar(hass, "on")
    assert shown == [] and hass.states.get(NOTE).state == "none"


# the door picture (A12/A41)
def jpeg(w=1200, h=900) -> str:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (200, 120, 40)).save(out, format="JPEG")
    return base64.b64encode(out.getvalue()).decode()


async def test_picture_becomes_a_grey_png_under_local_until_removed(hass: HomeAssistant, media, door):
    _, texts = door
    await setup(hass)
    res = await call(hass, "door_picture", {"image": jpeg()}, response=True)
    path = res["path"]
    assert path.startswith("/local/aikos_door/foto-") and path.endswith(".png")
    f = hass.config.path("www", "aikos_door", path.rsplit("/", 1)[1])
    img = Image.open(f)
    assert img.mode == "L" and img.width <= 492 and img.height <= 536 and len(img.getcolors(256)) <= 16
    assert texts[-1] == (PHOTO_URL, "http://192.0.2.10:8123" + path)
    assert hass.states.get(PICTURE).state == "shown" and hass.states.get(PICTURE).attributes["path"] == path
    second = (await call(hass, "door_picture", {"image": jpeg(400, 600)}, response=True))["path"]
    assert os.listdir(hass.config.path("www", "aikos_door")) == [second.rsplit("/", 1)[1]]   # the old one is gone
    await call(hass, "door_picture_clear")
    assert texts[-1] == (PHOTO_URL, "") and hass.states.get(PICTURE).state == "none"
    assert os.listdir(hass.config.path("www", "aikos_door")) == []
    with pytest.raises(ServiceValidationError):
        await call(hass, "door_picture", {"image": base64.b64encode(b"not a picture").decode()}, response=True)


# the greeting (A13/A26)
WAV = base64.b64encode(b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 40).decode()


async def test_greeting_text_only_within_its_window(hass: HomeAssistant, media, door, freezer):
    _, texts = door
    freezer.move_to(local(21, 14, 0))
    await setup(hass)
    await call(hass, "door_greeting", {"enabled": True, "text": "Willkommen!", "start": local(21, 15).isoformat(),
                                       "end": local(21, 16).isoformat()}, response=True)
    assert hass.states.get(GREETING).state == "scheduled" and hass.states.get(GREETING_TEXT).state == ""
    freezer.move_to(local(21, 15, 0))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(GREETING_TEXT).state == "Willkommen!" and hass.states.get(GREETING).state == "active"
    freezer.move_to(local(21, 16, 0))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(GREETING_TEXT).state == "" and hass.states.get(GREETING).state == "off"
    with pytest.raises(ServiceValidationError):
        await call(hass, "door_greeting", {"start": local(21, 18).isoformat(), "end": local(21, 17).isoformat()},
                   response=True)


async def test_greeting_sound_once_per_visit_not_in_a_call_and_not_over_a_note(hass: HomeAssistant, media, door, freezer,
                                                                              monkeypatch):
    from custom_components.aikos import door_speaker
    played = []

    async def fake_play(hass_, path):
        played.append(path.name)
        return 1.0
    monkeypatch.setattr(door_speaker, "play", fake_play)
    freezer.move_to(local(21, 14, 0))
    await setup(hass)
    await call(hass, "door_greeting", {"enabled": True, "text": "Hallo", "audio": WAV}, response=True)
    assert hass.states.get(GREETING).attributes["audio"] is True
    assert any(p.name.startswith("greeting-") and p.suffix == ".wav" for p in (media / "aikos").iterdir())
    await radar(hass, "on")
    assert len(played) == 1
    await radar(hass, "off")
    freezer.move_to(local(21, 14, 5))
    await radar(hass, "on")
    assert len(played) == 1                                                  # same visit (10 min)
    await radar(hass, "off")
    freezer.move_to(local(21, 14, 20))
    hass.states.async_set(CALL, "on")
    await radar(hass, "on")
    assert len(played) == 1                                                  # not during a call
    hass.states.async_set(CALL, "off")
    await radar(hass, "off")
    await call(hass, "door_say", {"message": "Komme gleich"})
    await radar(hass, "on")
    assert len(played) == 1                                                  # the note goes first, no sound on top
    await radar(hass, "off")
    await radar(hass, "on")
    assert len(played) == 2
    with pytest.raises(ServiceValidationError):
        await call(hass, "door_greeting", {"audio": base64.b64encode(b"plain text").decode()}, response=True)


async def test_door_state_survives_a_reload(hass: HomeAssistant, media, door, freezer):
    freezer.move_to(local(21, 14, 0))
    entry = await setup(hass)
    await call(hass, "bell_mute", {"minutes": 120})
    await call(hass, "door_say", {"message": "Bin im Garten"})
    await call(hass, "door_picture", {"image": jpeg()}, response=True)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(MUTED).state == "on" and hass.states.get(NOTE).state == "waiting"
    assert hass.states.get(PICTURE).state == "shown"


async def test_the_door_services_need_no_admin(hass: HomeAssistant, media, door, hass_read_only_user):
    await setup(hass)
    ctx = Context(user_id=hass_read_only_user.id)
    await call(hass, "bell_mute", {"minutes": 5}, context=ctx)
    await call(hass, "door_say", {"message": "Hallo"}, context=ctx)
    await call(hass, "door_greeting", {"enabled": False}, response=True, context=ctx)
    assert hass.states.get(MUTED).state == "on" and hass.states.get(NOTE).state == "waiting"
    await call(hass, "bell_unmute", context=ctx)
    assert hass.states.get(MUTED).state == "off"


@pytest.mark.enable_socket
async def test_the_sound_goes_to_the_door_after_the_door_allows_it(hass: HomeAssistant, monkeypatch):
    """door_speaker.play: allow_tts with this machine's address and the length, then RTP frames to the talk computer."""
    import asyncio
    import socket

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.aikos import door_speaker
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.setblocking(False)
    monkeypatch.setattr(door_speaker, "DOOR_PORT", rx.getsockname()[1])
    monkeypatch.setattr(door_speaker, "LEAD", 100)                       # no real-time pacing in the test

    async def pcm(path, max_s=door_speaker.MAX_S):
        return bytes([0, 1]) * door_speaker.FRAME * 5                       # 5 frames = 0.1 s
    monkeypatch.setattr(door_speaker, "decode", pcm)
    MockConfigEntry(domain="esphome", title="aikos-intercom-talk",
                    data={"host": "127.0.0.1", "device_name": "aikos-intercom-talk"}).add_to_hass(hass)
    allowed = async_mock_service(hass, "esphome", "aikos_intercom_talk_allow_tts")
    from pathlib import Path
    seconds = await door_speaker.play(hass, Path("greeting.wav"))
    await asyncio.sleep(0.05)
    got = []
    while True:
        try:
            got.append(rx.recv(2048))
        except BlockingIOError:
            break
    rx.close()
    assert round(seconds, 2) == 0.1 and allowed[0].data == {"host": "127.0.0.1", "ms": 2100}
    assert len(got) == 5 and all(len(f) == 12 + door_speaker.FRAME * 2 for f in got)


async def test_without_the_talk_computer_nothing_is_sent(hass: HomeAssistant):
    from pathlib import Path

    from custom_components.aikos import door_speaker
    with pytest.raises(door_speaker.DoorSpeakerError):
        await door_speaker.play(hass, Path("greeting.wav"))                  # no allow_tts action: the door is not there

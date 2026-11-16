"""The door's conversation as one thread (A49): ring, visitor, house, answers from the app (and whether they were read
aloud), waiting answers, announcements and messages, in order; it stays after the call; 5 minutes apart is a new visit;
kept over a restart."""
from datetime import timedelta

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import async_mock_service

DOMAIN = "aikos"
BELL = "event.test_doorbell"
SOMEONE = "binary_sensor.aikos_intercom_screen_someone_at_the_door"
THREAD = "sensor.aikos_door_thread"


@pytest.fixture
def media(hass: HomeAssistant, tmp_path):
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    return tmp_path / "media"


@pytest.fixture
def door(hass: HomeAssistant, media, monkeypatch):
    from custom_components.aikos import door_speaker, door_voice
    async_mock_service(hass, "esphome", "aikos_intercom_screen_show_reply")

    async def synthesize(hass_, engine, text, voice):
        if "kaputt" in text:
            raise RuntimeError("not faithful")
        return "mp3", b"ID3 " + text.encode()

    async def play(hass_, path):
        return 1.0
    monkeypatch.setattr(door_voice, "synthesize", synthesize)
    monkeypatch.setattr(door_speaker, "play", play)


async def setup(hass: HomeAssistant):
    hass.states.async_set(BELL, "2026-10-22T10:00:00.000+00:00", {"event_type": "pressed"})
    hass.states.async_set(SOMEONE, "off")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    entry = (await hass.config_entries.flow.async_configure(result["flow_id"], {}))["result"]
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"doorbell": BELL, "tts_engine": "tts.aikos_tts"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return entry


def entries(hass):
    return [(e["kind"], e["who"], e["text"]) for e in hass.states.get(THREAD).attributes["entries"]]


async def settle(hass):
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_everything_at_the_door_in_order_and_it_stays_after_the_call(hass: HomeAssistant, door):
    await setup(hass)
    hass.states.async_set(BELL, "2026-10-22T12:00:00.000+00:00", {"event_type": "pressed"})
    await settle(hass)
    hass.bus.async_fire("aikos_call_message", {"side": "door", "who": "Paketdienst", "text": "Ich habe ein Paket.", "lang": ""})
    hass.states.async_set(SOMEONE, "on")
    await settle(hass)
    await hass.services.async_call(DOMAIN, "door_say", {"message": "Bitte vor die Tür legen.", "sender": "Alex", "voice": "v1"},
                                   blocking=True, return_response=True)
    await settle(hass)
    hass.bus.async_fire("aikos_call_message", {"side": "room", "who": "Sam", "text": "Danke!", "lang": ""})
    hass.bus.async_fire("aikos_door_announced", {"situation": "quiet", "text": "Wir können gerade nicht."})
    hass.bus.async_fire("aikos_door_message_saved", {"file": "x.mp3", "seconds": 9.4, "url": ""})
    await settle(hass)
    assert entries(hass) == [("ring", "", "Es hat geklingelt"), ("door", "Paketdienst", "Ich habe ein Paket."),
                             ("reply", "Alex", "Bitte vor die Tür legen."), ("room", "Sam", "Danke!"),
                             ("announce", "Tür", "Wir können gerade nicht."),
                             ("message", "Besucher", "hat eine Nachricht hinterlassen (9 s)")]
    reply = hass.states.get(THREAD).attributes["entries"][2]
    assert reply["spoken"] is True                                              # read aloud in the sender's voice
    assert len({e["visit"] for e in hass.states.get(THREAD).attributes["entries"]}) == 1


async def test_a_waiting_answer_and_one_that_could_not_be_said(hass: HomeAssistant, door):
    await setup(hass)
    await hass.services.async_call(DOMAIN, "door_say", {"message": "Komme gleich.", "sender": "Alex"}, blocking=True,
                                   return_response=True)
    hass.states.async_set(SOMEONE, "on")
    await settle(hass)
    await hass.services.async_call(DOMAIN, "door_say", {"message": "Das ist kaputt.", "sender": "Alex", "voice": "v1"},
                                   blocking=True, return_response=True)
    await settle(hass)
    e = hass.states.get(THREAD).attributes["entries"]
    assert [(x["kind"], x["text"]) for x in e] == [("waiting", "Komme gleich."), ("reply", "Komme gleich."),
                                                   ("reply", "Das ist kaputt.")]                # the waiting one shown
    assert e[-1]["spoken"] is False                                             # shown, not read aloud (A46)


async def test_five_minutes_apart_is_a_new_visit_and_the_thread_survives_a_restart(hass: HomeAssistant, door, freezer):
    entry = await setup(hass)
    hass.bus.async_fire("aikos_call_message", {"side": "door", "who": "Besucher", "text": "Hallo?", "lang": ""})
    await settle(hass)
    freezer.tick(timedelta(minutes=6))
    hass.bus.async_fire("aikos_call_message", {"side": "door", "who": "Besucher", "text": "Noch jemand da?", "lang": ""})
    await settle(hass)
    visits = [e["visit"] for e in hass.states.get(THREAD).attributes["entries"]]
    assert visits[1] == visits[0] + 1 and hass.states.get(THREAD).attributes["visit"] == visits[1]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await settle(hass)
    assert [t for _, _, t in entries(hass)] == ["Hallo?", "Noch jemand da?"]


async def test_only_the_newest_60_entries_stay(hass: HomeAssistant, door):
    await setup(hass)
    for i in range(70):
        hass.bus.async_fire("aikos_call_message", {"side": "door", "who": "Besucher", "text": f"Satz {i}", "lang": ""})
    await settle(hass)
    texts = [t for _, _, t in entries(hass)]
    assert len(texts) == 60 and texts[0] == "Satz 10" and texts[-1] == "Satz 69"


WEBM = b"\x1aE\xdf\xa3" + b"\x00" * 64


async def voice(hass, sender="Alex", seconds=4.2, audio=WEBM):
    import base64
    return await hass.services.async_call(DOMAIN, "door_say_audio",
                                          {"audio": base64.b64encode(audio).decode(), "sender": sender, "seconds": seconds},
                                          blocking=True, return_response=True)


async def test_a_voice_message_plays_at_once_when_someone_is_there(hass: HomeAssistant, door, media, monkeypatch):
    from custom_components.aikos import door_speaker
    played = []

    async def play(hass_, path):
        played.append(path.name)
        return 1.0
    monkeypatch.setattr(door_speaker, "play", play)
    await setup(hass)
    hass.states.async_set(SOMEONE, "on")
    await settle(hass)
    assert await voice(hass) == {"delivered": "now"}
    await settle(hass)
    e = hass.states.get(THREAD).attributes["entries"][-1]
    assert (e["kind"], e["who"], e["seconds"], e["spoken"]) == ("voice", "Alex", 4.2, True)
    assert e["voice"].startswith("voice-") and e["voice"].endswith(".webm") and played == [e["voice"]]
    assert (media / "aikos" / e["voice"]).read_bytes() == WEBM            # stays: the chat can play it back


async def test_a_voice_message_waits_for_the_next_visitor(hass: HomeAssistant, door, media, monkeypatch):
    from custom_components.aikos import door_speaker
    played = []

    async def play(hass_, path):
        played.append(path.name)
        return 1.0
    monkeypatch.setattr(door_speaker, "play", play)
    await setup(hass)
    assert await voice(hass, seconds=7) == {"delivered": "waiting"}
    await settle(hass)
    waiting = hass.states.get(THREAD).attributes["entries"][-1]
    assert waiting["kind"] == "waiting" and waiting["voice"].startswith("voice-") and played == []
    assert hass.states.get("sensor.aikos_door_note").state == "waiting"
    hass.states.async_set(SOMEONE, "on")
    await settle(hass)
    e = hass.states.get(THREAD).attributes["entries"][-1]
    assert (e["kind"], e["voice"], e["spoken"]) == ("voice", waiting["voice"], True) and played == [waiting["voice"]]
    assert hass.states.get("sensor.aikos_door_note").state != "waiting"


async def test_a_voice_message_must_be_sound(hass: HomeAssistant, door, media):
    from homeassistant.exceptions import ServiceValidationError
    await setup(hass)
    with pytest.raises(ServiceValidationError):
        await voice(hass, audio=b"<html>not a sound</html>")
    assert not list((media / "aikos").glob("voice-*")) if (media / "aikos").exists() else True


async def test_lines_from_the_app_in_the_call_log_are_not_doubled(hass: HomeAssistant, door):
    await setup(hass)
    hass.bus.async_fire("aikos_call_message", {"side": "room", "who": "Alex", "text": "Bitte vor die Tür.", "via": "text"})
    hass.bus.async_fire("aikos_call_message", {"side": "room", "who": "Alex", "text": "Ich komme runter.", "via": "app"})
    hass.bus.async_fire("aikos_call_message", {"side": "room", "who": "Küche", "text": "Bin unterwegs.", "via": ""})
    await settle(hass)
    e = hass.states.get(THREAD).attributes["entries"]
    assert [(x["kind"], x["text"], x.get("via")) for x in e] == [("room", "Ich komme runter.", "app"),
                                                                 ("room", "Bin unterwegs.", None)]


async def test_what_was_said_stands_where_it_was_said(hass: HomeAssistant, door):
    await setup(hass)
    hass.bus.async_fire("aikos_call_message", {"side": "room", "who": "Alex", "text": "Ja?", "at": "2026-10-22T10:00:07+00:00"})
    hass.bus.async_fire("aikos_call_message", {"side": "door", "who": "Besucher", "text": "Ein langer Satz.",
                                               "at": "2026-10-22T10:00:01+00:00"})
    await settle(hass)
    assert [t for _, _, t in entries(hass)] == ["Ein langer Satz.", "Ja?"]

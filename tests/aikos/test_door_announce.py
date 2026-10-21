"""The door announcements in a real Home Assistant test instance (sprachausgabe S10–S14): made in advance in the saver's
voice, played after a ring when a situation applies and the level allows it; a parcel expected also speaks when someone
only comes close, instead of the greeting; nothing during a call; places only for residents who agreed."""
from datetime import timedelta

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

DOMAIN = "aikos"
BELL = "event.test_doorbell"
SOMEONE = "binary_sensor.aikos_intercom_screen_someone_at_the_door"
CALL = "binary_sensor.aikos_intercom_talk_in_call"
PARCEL = "input_boolean.aikos_test_parcel"
SENSOR = "sensor.aikos_door_announcements"
SENTENCES = {"parcel": "Bitte legen Sie das Paket vor die Tür.", "away": "Wir sind gerade nicht zu Hause.",
             "quiet": "Wir können gerade nicht an die Tür kommen."}


@pytest.fixture
def media(hass: HomeAssistant, tmp_path):
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    return tmp_path / "media"


@pytest.fixture
def door(hass: HomeAssistant, media, monkeypatch):
    """The screen, the voice service and the door speaker as test doubles; no waiting after the ring."""
    from custom_components.aikos import door_announce, door_speaker, door_voice
    async_mock_service(hass, "esphome", "aikos_intercom_screen_show_reply")
    monkeypatch.setattr(door_announce, "RING_DELAY", 0)
    spoken, played = [], []

    async def synthesize(hass_, engine, text, voice):
        spoken.append((text, voice))
        return "mp3", b"ID3 " + text.encode()

    async def play(hass_, path):
        played.append(path.read_bytes().removeprefix(b"ID3 ").decode())
        return 1.0
    monkeypatch.setattr(door_voice, "synthesize", synthesize)
    monkeypatch.setattr(door_speaker, "play", play)
    return spoken, played


async def setup(hass: HomeAssistant, a="not_home", b="not_home"):
    hass.states.async_set(BELL, "2026-10-21T10:00:00.000+00:00", {"event_type": "pressed"})
    hass.states.async_set(SOMEONE, "off")
    hass.states.async_set(PARCEL, "off")
    hass.states.async_set("person.a", a, {"friendly_name": "Alex"})
    hass.states.async_set("person.b", b, {"friendly_name": "Sam"})
    hass.states.async_set("zone.aikos_test_laden", "0", {"friendly_name": "Laden"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    entry = (await hass.config_entries.flow.async_configure(result["flow_id"], {}))["result"]
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "doorbell": BELL, "residents": ["person.a", "person.b"], "tts_engine": "tts.aikos_tts", "parcel_sensor": PARCEL})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    q = entry.runtime_data.quiet_hours
    q.update(enabled=False)                        # by day in these tests, whatever the clock says
    return entry


async def call(hass, service, data, response=False):
    r = await hass.services.async_call(DOMAIN, service, data, blocking=True, return_response=response)
    await hass.async_block_till_done(wait_background_tasks=True)
    return r


async def save(hass, level, **more):
    return await call(hass, "door_announcements", {"disclosure": level, "voice": "v1", **SENTENCES, **more}, True)


async def ring(hass, n=1):
    hass.states.async_set(BELL, f"2026-10-21T12:00:{n:02d}.000+00:00", {"event_type": "pressed"})
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_the_sentences_are_made_ahead_and_play_at_once_after_a_ring(hass: HomeAssistant, door):
    spoken, played = door
    await setup(hass)
    await save(hass, 1)
    assert sorted(t for t, _ in spoken) == sorted(SENTENCES.values())        # all three made now, in the saver's voice
    assert {v for _, v in spoken} == {"v1"}
    spoken.clear()
    await ring(hass)
    assert played == ["Wir sind gerade nicht zu Hause."] and spoken == []      # from the file made ahead, nothing made now
    st = hass.states.get(SENSOR)
    assert st.state == "away" and st.attributes["last"]["text"] == "Wir sind gerade nicht zu Hause."


async def test_level_0_says_nothing_and_makes_nothing(hass: HomeAssistant, door):
    spoken, played = door
    await setup(hass)
    await save(hass, 0)
    await ring(hass)
    assert spoken == [] and played == []
    assert hass.states.get(SENSOR).state == "none"


async def test_someone_home_and_the_bell_on_gets_nothing(hass: HomeAssistant, door):
    _, played = door
    await setup(hass, a="home")
    await save(hass, 1)
    await ring(hass)
    assert played == []


async def test_bell_muted_gets_the_quiet_sentence(hass: HomeAssistant, door):
    _, played = door
    await setup(hass, a="home")
    await save(hass, 1)
    await call(hass, "bell_mute", {"minutes": 30})
    await ring(hass)
    assert played == ["Wir können gerade nicht an die Tür kommen."]


async def test_a_second_ring_within_a_minute_is_not_answered_again(hass: HomeAssistant, door):
    _, played = door
    await setup(hass)
    await save(hass, 1)
    await ring(hass, 1)
    await ring(hass, 2)
    assert played == ["Wir sind gerade nicht zu Hause."]


async def test_nothing_during_a_call(hass: HomeAssistant, door):
    _, played = door
    await setup(hass)
    await save(hass, 1)
    hass.states.async_set(CALL, "on")
    await ring(hass)
    assert played == []


async def test_level_4_tells_the_place_only_of_who_agreed(hass: HomeAssistant, door):
    spoken, played = door
    await setup(hass, a="Laden", b="Laden")
    await save(hass, 4, away_places="Wir sind unterwegs. {wo}.", places={"zone.aikos_test_laden": "beim Laden"}, named=["person.a"])
    assert ("Wir sind unterwegs. Alex ist beim Laden.", "v1") in spoken
    await ring(hass)
    assert played == ["Wir sind unterwegs. Alex ist beim Laden."]            # Sam did not agree: not named


async def test_residents_moving_make_the_sentence_again_after_they_settle(hass: HomeAssistant, door):
    spoken, played = door
    await setup(hass, a="not_home", b="not_home")
    await save(hass, 4, away_places="Wir sind unterwegs. {wo}.", places={"zone.aikos_test_laden": "beim Laden"}, named=["person.a"])
    spoken.clear()
    hass.states.async_set("person.a", "Laden", {"friendly_name": "Alex"})
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["now_text"] == "Wir sind unterwegs. Alex ist beim Laden."
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert spoken == [("Wir sind unterwegs. Alex ist beim Laden.", "v1")]
    await ring(hass)
    assert played == ["Wir sind unterwegs. Alex ist beim Laden."]


async def test_a_ring_before_the_new_sentence_is_ready_says_it_anyway(hass: HomeAssistant, door):
    spoken, played = door
    await setup(hass)
    await save(hass, 4, away_places="Wir sind unterwegs. {wo}.", places={"zone.aikos_test_laden": "beim Laden"}, named=["person.a"])
    hass.states.async_set("person.a", "Laden", {"friendly_name": "Alex"})
    await ring(hass)                                                          # before the residents settled
    assert played == ["Wir sind unterwegs. Alex ist beim Laden."]


async def test_parcel_expected_speaks_when_someone_comes_close_instead_of_the_greeting(hass: HomeAssistant, door):
    spoken, played = door
    await setup(hass, a="home")
    await save(hass, 1)
    await call(hass, "door_greeting", {"enabled": True, "text": "Willkommen", "clear_window": True, "voice": "v1"})
    hass.states.async_set(PARCEL, "on")
    hass.states.async_set(SOMEONE, "on")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert played == ["Bitte legen Sie das Paket vor die Tür."]               # not the greeting on top
    await ring(hass)
    assert played == ["Bitte legen Sie das Paket vor die Tür."]               # the courier rings right after: not again


async def test_without_a_parcel_the_greeting_plays_as_before(hass: HomeAssistant, door):
    _, played = door
    await setup(hass, a="home")
    await save(hass, 1)
    await call(hass, "door_greeting", {"enabled": True, "text": "Willkommen", "clear_window": True, "voice": "v1"})
    hass.states.async_set(SOMEONE, "on")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert played == ["Willkommen"]


async def test_the_slider_sets_the_level(hass: HomeAssistant, door):
    _, played = door
    await setup(hass)
    await save(hass, 0)
    await hass.services.async_call("number", "set_value", {"entity_id": "number.aikos_door_disclosure", "value": 1},
                                   blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("number.aikos_door_disclosure").state == "1"
    await ring(hass)
    assert played == ["Wir sind gerade nicht zu Hause."]


async def test_bad_settings_are_refused(hass: HomeAssistant, door):
    await setup(hass)
    with pytest.raises(ServiceValidationError):
        await call(hass, "door_announcements", {"away_places": "Wir sind unterwegs."})       # {wo} missing
    with pytest.raises(ServiceValidationError):
        await call(hass, "door_announcements", {"away": "Hier {wo}"})


async def test_settings_and_made_sentences_survive_a_reload(hass: HomeAssistant, door):
    spoken, played = door
    entry = await setup(hass)
    await save(hass, 1)
    spoken.clear()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert spoken == []                                                       # nothing made again
    await ring(hass)
    assert played == ["Wir sind gerade nicht zu Hause."]

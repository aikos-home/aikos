"""Reading aloud at the door in the sender's own voice (aikos-app A42–A45): only with a voice service and a voice; a note
now is spoken right after it is shown, a waiting note and the greeting are made in advance and play at once; without a
voice only the text is shown; the voice service failing never breaks the door."""
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

DOMAIN = "aikos"
SOMEONE = "binary_sensor.aikos_intercom_screen_someone_at_the_door"
ENGINE = "tts.aikos_tts"


@pytest.fixture
def media(hass: HomeAssistant, tmp_path):
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    return tmp_path / "media"


@pytest.fixture
def door(hass: HomeAssistant, monkeypatch):
    """The screen, a voice service and the door speaker, as test doubles."""
    from custom_components.aikos import door_speaker, door_voice
    shown = async_mock_service(hass, "esphome", "aikos_intercom_screen_show_reply")
    hass.states.async_set(SOMEONE, "off")
    spoken, played = [], []

    async def synthesize(hass_, engine, text, voice):
        if voice == "broken":
            raise RuntimeError("voice service away")
        spoken.append((engine, text, voice))
        return "mp3", b"ID3 speech of " + text.encode()

    async def play(hass_, path):
        played.append(path.read_bytes())
        return 1.0
    monkeypatch.setattr(door_voice, "synthesize", synthesize)
    monkeypatch.setattr(door_speaker, "play", play)
    return shown, spoken, played


async def setup(hass: HomeAssistant, engine=ENGINE):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    if engine:
        hass.config_entries.async_update_entry(entry, options={**entry.options, "tts_engine": engine})
        await hass.async_block_till_done()
    return entry


async def call(hass, service, data, response=False):
    r = await hass.services.async_call(DOMAIN, service, data, blocking=True, return_response=response)
    await hass.async_block_till_done(wait_background_tasks=True)   # speech is made in the background
    return r


async def radar(hass, state):
    hass.states.async_set(SOMEONE, state)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_a_note_now_is_read_in_the_senders_voice(hass: HomeAssistant, media, door):
    shown, spoken, played = door
    await setup(hass)
    await radar(hass, "on")
    assert await call(hass, "door_say", {"message": "Komme sofort", "sender": "Alex", "voice": "v1"}, True) == {"delivered": "now"}
    assert [c.data["message"] for c in shown] == ["Komme sofort"]
    assert spoken == [(ENGINE, "Komme sofort", "v1")] and played == [b"ID3 speech of Komme sofort"]
    assert not any((media / "aikos").glob("speech-now-*"))                     # the one-off speech is gone after playing


async def test_a_waiting_note_is_made_ahead_and_plays_at_once(hass: HomeAssistant, media, door):
    shown, spoken, played = door
    await setup(hass)
    await call(hass, "door_say", {"message": "Paket in die Box", "sender": "Alex", "voice": "v1"}, True)
    assert spoken == [(ENGINE, "Paket in die Box", "v1")] and played == []      # made now, played later
    assert len(list((media / "aikos").glob("speech-note-*"))) == 1
    await radar(hass, "on")
    assert played == [b"ID3 speech of Paket in die Box"] and len(spoken) == 1
    assert not any((media / "aikos").glob("speech-note-*"))


async def test_without_a_voice_or_service_only_the_text_is_shown(hass: HomeAssistant, media, door):
    shown, spoken, played = door
    await setup(hass)
    await radar(hass, "on")
    await call(hass, "door_say", {"message": "Hallo", "sender": "Kim"}, True)    # Kim has no voice (A45)
    assert len(shown) == 1 and spoken == [] and played == []


async def test_no_voice_service_set_up_means_text_only(hass: HomeAssistant, media, door):
    shown, spoken, played = door
    await setup(hass, engine="")
    await radar(hass, "on")
    await call(hass, "door_say", {"message": "Hallo", "voice": "v1"}, True)
    assert len(shown) == 1 and spoken == [] and played == []


async def test_a_broken_voice_service_never_breaks_the_door(hass: HomeAssistant, media, door):
    shown, spoken, played = door
    await setup(hass)
    assert await call(hass, "door_say", {"message": "Hallo", "voice": "broken"}, True) == {"delivered": "waiting"}
    await radar(hass, "on")
    assert [c.data["message"] for c in shown] == ["Hallo"] and played == []


async def test_greeting_text_is_read_in_the_savers_voice_unless_a_sound_was_recorded(hass: HomeAssistant, media, door):
    shown, spoken, played = door
    await setup(hass)
    await call(hass, "door_greeting", {"enabled": True, "text": "Willkommen!", "voice": "v1"}, True)
    assert spoken == [(ENGINE, "Willkommen!", "v1")]
    st = hass.states.get("sensor.aikos_door_greeting")
    assert st.state == "active"
    await radar(hass, "on")
    assert played == [b"ID3 speech of Willkommen!"]
    await call(hass, "door_greeting", {"text": "Hallo zusammen"}, True)           # new text: made again
    assert spoken[-1] == (ENGINE, "Hallo zusammen", "v1") and len(list((media / "aikos").glob("speech-greeting-*"))) == 1
    wav = "UklGRiQAAABXQVZFZm10IAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
    await call(hass, "door_greeting", {"audio": wav}, True)                       # a recorded sound goes first
    g = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.door_actions.state.greeting
    assert g.sound == g.audio and g.audio.startswith("greeting-")


async def test_a_note_replaced_or_withdrawn_takes_its_speech_with_it(hass: HomeAssistant, media, door):
    shown, spoken, played = door
    await setup(hass)
    await call(hass, "door_say", {"message": "Erste", "voice": "v1"}, True)
    await call(hass, "door_say", {"message": "Zweite", "voice": "v1"}, True)
    files = list((media / "aikos").glob("speech-note-*"))
    assert len(files) == 1 and files[0].read_bytes() == b"ID3 speech of Zweite"
    await call(hass, "door_say_cancel", {}, True)
    assert not any((media / "aikos").glob("speech-note-*"))
    await radar(hass, "on")
    assert shown == [] and played == []

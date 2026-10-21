"""The door message register in a real Home Assistant test instance: door events → entity and service, delete with the
MP3, heard, older files adopted, survives a reload, callable without admin rights."""
import os

import pytest
from homeassistant import config_entries
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import async_capture_events

DOMAIN = "aikos"
SENSOR = "sensor.aikos_door_messages"
RECORDING, DOOR = "binary_sensor.aikos_intercom_talk_message_recording", "sensor.talk_transcript_door"
NAME = "nachricht-20261021-084712.mp3"


@pytest.fixture
def media(hass: HomeAssistant, tmp_path):
    hass.config.media_dirs = {"local": str(tmp_path)}
    folder = tmp_path / "aikos_door"
    folder.mkdir()
    return folder


async def setup(hass: HomeAssistant):
    hass.states.async_set(RECORDING, "off")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    return hass.config_entries.async_entries(DOMAIN)[0]


async def door_message(hass, folder, name=NAME, recipient="Alex", words=("Hallo, hier ist die Post.",)):
    hass.bus.async_fire("esphome.aikos_door_message", {"recipient": recipient, "source": "screen"})
    hass.states.async_set(RECORDING, "on")
    await hass.async_block_till_done()
    for i, said in enumerate(words):
        hass.states.async_set(DOOR, f"2026-10-21T08:47:0{i + 2}+02:00", {"message": said, "speaker": "Paketdienst"})
        await hass.async_block_till_done()
    hass.states.async_set(RECORDING, "off")
    (folder / name).write_bytes(b"ID3 fake mp3")
    hass.bus.async_fire("aikos_door_message_saved", {"file": name, "seconds": 9.4, "url": "/media/local/x?authSig=y",
                                                     "recipient": ""})
    await hass.async_block_till_done()


async def listing(hass, context=None):
    res = await hass.services.async_call(DOMAIN, "door_messages", {}, blocking=True, return_response=True, context=context)
    return res["messages"]


async def test_a_door_message_lands_in_the_register_with_recipient_and_words(hass: HomeAssistant, media):
    await setup(hass)
    assert hass.states.get(SENSOR).state == "0"
    await door_message(hass, media)
    state = hass.states.get(SENSOR)
    assert state.state == "1" and state.attributes["newest"] == NAME[:-4] and state.attributes["revision"] == 1
    [m] = await listing(hass)
    assert (m["id"], m["file"], m["seconds"], m["recipient"], m["speaker"]) == (NAME[:-4], NAME, 9.4, "Alex", "Paketdienst")
    assert m["text"] == "Hallo, hier ist die Post." and m["heard_by"] == [] and m["file_missing"] is False
    assert "url" not in m                       # no signed Home Assistant link in the register


async def test_late_words_change_the_revision(hass: HomeAssistant, media):
    await setup(hass)
    await door_message(hass, media)
    rev = hass.states.get(SENSOR).attributes["revision"]
    hass.states.async_set(DOOR, "2026-10-21T08:47:30+02:00", {"text": "Schönen Tag noch.", "speaker": ""})
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["revision"] == rev + 1
    assert (await listing(hass))[0]["text"] == "Hallo, hier ist die Post. Schönen Tag noch."


async def test_delete_removes_the_mp3_and_the_entry_and_writes_the_logbook(hass: HomeAssistant, media):
    await setup(hass)
    await door_message(hass, media)
    logged = []
    hass.services.async_register("logbook", "log", lambda call: logged.append(call.data))
    res = await hass.services.async_call(DOMAIN, "door_message_delete", {"id": NAME[:-4], "by": "Alex"}, blocking=True,
                                         return_response=True)
    await hass.async_block_till_done()
    assert res == {"deleted": NAME[:-4]} and not (media / NAME).exists()
    assert await listing(hass) == [] and hass.states.get(SENSOR).state == "0"
    assert "(Alex)" in logged[0]["message"]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "door_message_delete", {"id": NAME[:-4]}, blocking=True, return_response=True)


async def test_heard_is_noted_once_per_person(hass: HomeAssistant, media):
    await setup(hass)
    await door_message(hass, media)
    for by in ("Alex", "Alex", "Kim"):
        await hass.services.async_call(DOMAIN, "door_message_heard", {"id": NAME[:-4], "by": by}, blocking=True)
    assert (await listing(hass))[0]["heard_by"] == ["Alex", "Kim"]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "door_message_heard", {"id": "nope", "by": "Alex"}, blocking=True)


async def test_older_files_are_adopted_and_a_missing_file_is_marked(hass: HomeAssistant, media):
    old = media / "nachricht-20261020-101010.mp3"
    old.write_bytes(b"ID3")
    os.utime(old, (1760954400, 1760954400))
    (media / "begruessung.mp3").write_bytes(b"ID3")
    await setup(hass)
    [m] = await listing(hass)
    assert m["id"] == "nachricht-20261020-101010" and m["adopted"] is True and m["time"] == "2025-10-20T10:00:00+00:00"
    old.unlink()
    [m] = await listing(hass)
    assert m["file_missing"] is True             # the entry stays (no automatic deletion), the app can show or delete it


async def test_register_survives_a_reload(hass: HomeAssistant, media):
    entry = await setup(hass)
    await door_message(hass, media)
    await hass.services.async_call(DOMAIN, "door_message_heard", {"id": NAME[:-4], "by": "Alex"}, blocking=True)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    [m] = await listing(hass)
    assert m["text"] == "Hallo, hier ist die Post." and m["recipient"] == "Alex" and m["heard_by"] == ["Alex"]
    assert m["adopted"] is False


async def test_a_bad_file_name_is_ignored(hass: HomeAssistant, media):
    await setup(hass)
    hass.bus.async_fire("aikos_door_message_saved", {"file": "../../config/secrets.mp3", "seconds": 3})
    await hass.async_block_till_done()
    assert await listing(hass) == [] and hass.states.get(SENSOR).state == "0"


async def test_the_services_need_no_admin(hass: HomeAssistant, media, hass_read_only_user):
    await setup(hass)
    await door_message(hass, media)
    ctx = Context(user_id=hass_read_only_user.id)
    assert len(await listing(hass, ctx)) == 1
    await hass.services.async_call(DOMAIN, "door_message_heard", {"id": NAME[:-4], "by": "Kim"}, blocking=True, context=ctx)
    await hass.services.async_call(DOMAIN, "door_message_delete", {"id": NAME[:-4], "by": "Kim"}, blocking=True, context=ctx)
    assert await listing(hass, ctx) == []


async def test_nothing_from_the_door_fires_a_call_message(hass: HomeAssistant, media):
    """The register only listens; the call log stays as it is (no call is running)."""
    await setup(hass)
    events = async_capture_events(hass, "aikos_call_message")
    await door_message(hass, media)
    assert events == [] and hass.states.get("sensor.aikos_call_log").attributes["messages"] == []

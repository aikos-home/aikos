"""The call log sensors in a real Home Assistant test instance: wiring, R22 around call start/end, events, test isolation, restore."""
import json

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import async_capture_events, mock_restore_cache

DOMAIN = "aikos"
LIVE, TEST = "sensor.aikos_call_log", "sensor.aikos_call_log_test"
CALL, DOOR, ROOM = "binary_sensor.aikos_intercom_talk_in_call", "sensor.talk_transcript_door", "sensor.talk_transcript"
TCALL, TDOOR, TBUTTON = "input_boolean.aikos_test_in_call", "sensor.talk_transcript_door_test", "input_button.aikos_test_new_call"
VISITOR = {"text": "Guten Tag, Paketdienst von DHL.", "message": "Guten Tag.", "speaker": "Paketdienst · DHL",
           "speaker_role": "parcel", "urgent": False, "language": "de"}


async def setup(hass: HomeAssistant):
    for e, s in ((CALL, "off"), (TCALL, "off")):
        hass.states.async_set(e, s)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()


async def set_state(hass, entity, state, **attrs):
    hass.states.async_set(entity, state, attrs)
    await hass.async_block_till_done()


def attrs(hass, entity):
    return hass.states.get(entity).attributes


async def test_live_call_collects_announces_and_empties_at_the_end(hass: HomeAssistant):
    await setup(hass)
    events = async_capture_events(hass, "aikos_call_message")
    await set_state(hass, DOOR, "2026-10-02T12:00:01+02:00", **VISITOR)          # outside a call: not added (R22)
    assert attrs(hass, LIVE)["messages"] == []
    await set_state(hass, CALL, "on")
    a = attrs(hass, LIVE)
    assert a["active"] is True and a["call_id"] and a["messages_json"] == "[]"
    await set_state(hass, DOOR, "2026-10-02T12:00:05+02:00", **VISITOR)
    await set_state(hass, ROOM, "2026-10-02T12:00:09+02:00", text="Ich komme.", speaker="Alex", device="Key A")
    a = attrs(hass, LIVE)
    assert [m["side"] for m in a["messages"]] == ["door", "room"]
    assert hass.states.get(LIVE).state == "2026-10-02T12:00:09+02:00"
    assert [m["id"] for m in json.loads(a["messages_json"])] == ["door-2026-10-02T12:00:05+02:00", "room-2026-10-02T12:00:09+02:00"]
    assert [e.data["who"] for e in events] == ["Paketdienst · DHL", "Alex"]
    await set_state(hass, DOOR, "2026-10-02T12:00:05+02:00", **dict(VISITOR, language="en", language_name="Englisch"))
    assert len(events) == 2                                                    # a replaced message is no new message
    await set_state(hass, CALL, "off")
    a = attrs(hass, LIVE)
    assert a["messages"] == [] and a["active"] is False and a["messages_json"] == "[]"


async def test_test_log_never_moves_the_live_log(hass: HomeAssistant):
    await setup(hass)
    events = async_capture_events(hass, "aikos_call_message")
    live_before = hass.states.get(LIVE).last_updated
    await set_state(hass, TBUTTON, "2026-10-02T12:10:00+00:00")
    assert attrs(hass, TEST)["call_id"] == "2026-10-02T12:10:00+00:00"
    await set_state(hass, TCALL, "on")
    await set_state(hass, TDOOR, "2026-10-02T12:10:05+02:00", **VISITOR)
    assert len(attrs(hass, TEST)["messages"]) == 1
    assert hass.states.get(LIVE).last_updated == live_before and events == []   # no live update, no event from tests


async def test_restore_keeps_the_running_chat(hass: HomeAssistant):
    msg = {"id": "door-t1", "t": "t1", "side": "door", "who": "Besucher", "role": "", "text": "Hallo", "urgent": False,
           "lang": "", "spk": "", "dev": "", "sticky": False}
    mock_restore_cache(hass, [State(LIVE, "t1", {"call_id": "c1", "messages": [msg]})])
    await setup(hass)
    a = attrs(hass, LIVE)
    assert a["call_id"] == "c1" and [m["id"] for m in a["messages"]] == ["door-t1"] and hass.states.get(LIVE).state == "t1"

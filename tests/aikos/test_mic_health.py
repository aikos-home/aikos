"""W3 in the integration: rules (two bad in a row = problem, first ok clears) and the problem sensors in Home Assistant."""
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.aikos.mic_health import CLEARED, PROBLEM, MicHealth, message

LIVE, TEST = "binary_sensor.aikos_mic_problem", "binary_sensor.aikos_mic_problem_test"


def test_two_bad_in_a_row_then_the_first_ok_clears():
    h = MicHealth()
    assert h.note("Key A", "silent", "t1", {}) is None                 # one bad recording: no warning yet
    assert h.note("Key A", "silent", "t2", {}) == PROBLEM
    assert h.note("Key A", "silent", "t3", {}) is None                 # still bad: no second warning
    assert h.problem_devices == ["Key A"]
    assert h.note("Key A", "ok", "t4", {}) == CLEARED
    assert h.problem_devices == []


def test_an_ok_in_between_resets_the_count_and_devices_are_separate():
    h = MicHealth()
    h.note("Key A", "clipping", "t1", {})
    h.note("Key A", "ok", "t2", {})
    assert h.note("Key A", "clipping", "t3", {}) is None
    assert h.note("Key B", "silent", "t3", {}) is None
    assert h.problem_devices == []


def test_message_in_the_house_language():
    assert message("aikos RoomKey Touch", "silent", "de") == ("aikos: Mikro", "Mikro an aikos RoomKey Touch sendet nur Stille – Kabel prüfen")
    assert message("Door", "clipping", "en")[1] == "Mic at Door is clipping – check its wiring"


async def setup(hass: HomeAssistant):
    hass.config.language = "de"
    created = async_mock_service(hass, "persistent_notification", "create")
    dismissed = async_mock_service(hass, "persistent_notification", "dismiss")
    pushed = async_mock_service(hass, "notify", "aikos_phone_a")
    result = await hass.config_entries.flow.async_init("aikos", context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    entry = result["result"]
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {"notify_targets": ["notify.aikos_phone_a"]})
    await hass.async_block_till_done()
    return created, dismissed, pushed


async def check(hass, verdict, device="aikos RoomKey Touch", event="aikos_mic_check"):
    hass.bus.async_fire(event, {"device": device, "verdict": verdict, "peak_db": -120.0, "zero_ratio": 1.0})
    await hass.async_block_till_done()


async def test_dead_mic_warns_once_and_clears(hass: HomeAssistant):
    created, dismissed, pushed = await setup(hass)
    await check(hass, "silent")
    assert hass.states.get(LIVE).state == "off" and created == []
    await check(hass, "silent")
    state = hass.states.get(LIVE)
    assert state.state == "on" and state.attributes["problem_devices"] == ["aikos RoomKey Touch"]
    assert state.attributes["devices"]["aikos RoomKey Touch"]["peak_db"] == -120.0
    assert [c.data["notification_id"] for c in created] == ["aikos_mic_aikos_roomkey_touch"]
    assert pushed[0].data["message"] == "Mikro an aikos RoomKey Touch sendet nur Stille – Kabel prüfen"
    await check(hass, "silent")
    assert len(created) == 1 and len(pushed) == 1                     # no repeat while it stays broken
    await check(hass, "ok")
    assert hass.states.get(LIVE).state == "off"
    assert [c.data["notification_id"] for c in dismissed] == ["aikos_mic_aikos_roomkey_touch"]


async def test_bench_events_only_reach_the_test_sensor(hass: HomeAssistant):
    created, _, pushed = await setup(hass)
    await check(hass, "silent", event="aikos_mic_check_test")
    await check(hass, "silent", event="aikos_mic_check_test")
    assert hass.states.get(TEST).state == "on"
    assert hass.states.get(LIVE).state == "off" and created == [] and pushed == []

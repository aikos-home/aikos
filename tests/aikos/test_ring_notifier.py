"""Ring push in a real Home Assistant test instance (KR8, KR-R3, KR-R12): options, doorbell, residents, notify targets."""
from datetime import datetime

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

DOMAIN = "aikos"
BELL = "event.test_doorbell"
PRESS = "binary_sensor.aikos_doorbell_button"


def local(hour, minute=0, second=0):
    return datetime(2026, 10, 2, hour, minute, second, tzinfo=dt_util.get_default_time_zone())


async def setup(hass: HomeAssistant, doorbell=BELL, residents=("person.a", "person.b"), notify=("notify.aikos_phone_a", "notify.aikos_phone_b")):
    hass.config.language = "de"
    calls_a = async_mock_service(hass, "notify", "aikos_phone_a")
    calls_b = async_mock_service(hass, "notify", "aikos_phone_b")
    hass.states.async_set(BELL, "2026-10-02T10:00:00.000+00:00", {"event_type": "pressed"})
    hass.states.async_set(PRESS, "off")
    hass.states.async_set("person.a", "home")
    hass.states.async_set("person.b", "home")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    entry = result["result"]
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"doorbell": doorbell, "residents": list(residents), "notify_targets": list(notify)})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return entry, calls_a, calls_b


async def ring(hass, n):
    hass.states.async_set(BELL, f"2026-10-02T12:00:{n:02d}.000+00:00", {"event_type": "pressed"})
    await hass.async_block_till_done()


async def test_ring_in_quiet_hours_pushes_both_phones(hass: HomeAssistant, freezer):
    freezer.move_to(local(22, 14))
    _, a, b = await setup(hass)
    await ring(hass, 1)
    assert len(a) == 1 and len(b) == 1
    assert a[0].data == {"title": "aikos", "message": "Es hat geklingelt (22:14) · Ruhezeit"}


async def test_ring_by_day_with_someone_home_pushes_nothing(hass: HomeAssistant, freezer):
    freezer.move_to(local(14))
    _, a, b = await setup(hass)
    await ring(hass, 1)
    assert a == [] and b == []


async def test_ring_by_day_with_nobody_home_pushes(hass: HomeAssistant, freezer):
    freezer.move_to(local(14))
    _, a, _ = await setup(hass)
    hass.states.async_set("person.a", "not_home")
    hass.states.async_set("person.b", "Arbeit")
    await ring(hass, 1)
    assert len(a) == 1 and a[0].data["message"].endswith("niemand zu Hause")


async def test_storm_ringing_is_one_push_then_again_after_30_s(hass: HomeAssistant, freezer):
    freezer.move_to(local(22))
    _, a, _ = await setup(hass)
    for n in range(1, 6):
        await ring(hass, n)
    assert len(a) == 1
    freezer.move_to(local(22, 0, 31))
    await ring(hass, 9)
    assert len(a) == 2


async def test_device_coming_back_is_no_ring(hass: HomeAssistant, freezer):
    freezer.move_to(local(22))
    _, a, _ = await setup(hass)
    hass.states.async_set(BELL, "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set(BELL, "2026-10-02T10:00:00.000+00:00", {"event_type": "pressed"})
    await hass.async_block_till_done()
    assert a == []


async def test_binary_sensor_doorbell(hass: HomeAssistant, freezer):
    freezer.move_to(local(22))
    _, a, _ = await setup(hass, doorbell=PRESS)
    hass.states.async_set(PRESS, "on")
    await hass.async_block_till_done()
    hass.states.async_set(PRESS, "off")
    await hass.async_block_till_done()
    assert len(a) == 1


async def test_quiet_hours_off_by_day_rule_only(hass: HomeAssistant, freezer):
    freezer.move_to(local(22))
    _, a, _ = await setup(hass)
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.aikos_quiet_hours"}, blocking=True)
    await ring(hass, 1)
    assert a == []                                                       # everybody home, quiet hours off


async def test_missing_phone_does_not_stop_the_others(hass: HomeAssistant, freezer):
    freezer.move_to(local(22))
    _, a, _ = await setup(hass, notify=("notify.aikos_gone_phone", "notify.aikos_phone_a"))
    await ring(hass, 1)
    assert len(a) == 1


async def test_options_keep_quiet_hours_and_can_be_cleared(hass: HomeAssistant, freezer):
    freezer.move_to(local(22))
    entry, a, _ = await setup(hass)
    await hass.services.async_call("time", "set_value", {"entity_id": "time.aikos_quiet_hours_start", "time": "21:00:00"}, blocking=True)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})   # everything cleared
    await hass.async_block_till_done()
    assert "doorbell" not in entry.options and entry.options["quiet_hours_start"] == "21:00:00"
    await ring(hass, 1)
    assert a == []                                                       # no doorbell any more → no push

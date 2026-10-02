"""The aikos integration in a real Home Assistant test instance (KR1, KR2, KR-R8)."""
import json
from datetime import datetime
from pathlib import Path

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

DOMAIN = "aikos"
MANIFEST_VERSION = json.loads((Path(__file__).parents[2] / "custom_components/aikos/manifest.json").read_text())["version"]
SWITCH, START, END, ACTIVE = ("switch.aikos_quiet_hours", "time.aikos_quiet_hours_start", "time.aikos_quiet_hours_end",
                              "binary_sensor.aikos_quiet_hours")


def local(hour, minute=0, second=0):
    return datetime(2026, 10, 2, hour, minute, second, tzinfo=dt_util.get_default_time_zone())


async def setup(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return result["result"]


async def set_time(hass, entity_id, value):
    await hass.services.async_call("time", "set_value", {"entity_id": entity_id, "time": value}, blocking=True)


async def test_setup_creates_the_aikos_device_with_fixed_ids_and_defaults(hass: HomeAssistant, freezer):
    freezer.move_to(local(14))
    entry = await setup(hass)
    assert hass.states.get(SWITCH).state == "on"                      # requirement 1: quiet hours on by default
    assert hass.states.get(START).state == "20:00:00"
    assert hass.states.get(END).state == "07:00:00"
    assert hass.states.get(ACTIVE).state == "off"
    assert hass.states.get(ACTIVE).attributes["start"] == "20:00"
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert [(d.name, d.manufacturer, d.sw_version) for d in devices] == [("aikos", "aikos-home", MANIFEST_VERSION)]


async def test_only_one_aikos(hass: HomeAssistant):
    await setup(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT


async def test_active_switches_exactly_at_start_and_end(hass: HomeAssistant, freezer):
    freezer.move_to(local(19, 59, 50))
    await setup(hass)
    assert hass.states.get(ACTIVE).state == "off"
    freezer.move_to(local(20, 0, 0))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(ACTIVE).state == "on"
    freezer.move_to(datetime(2026, 10, 3, 7, 0, 0, tzinfo=dt_util.get_default_time_zone()))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(ACTIVE).state == "off"


async def test_changing_the_settings_takes_effect_at_once(hass: HomeAssistant, freezer):
    freezer.move_to(local(14))
    await setup(hass)
    await set_time(hass, START, "13:00:00")
    await set_time(hass, END, "15:00:00")
    assert hass.states.get(ACTIVE).state == "on"
    assert hass.states.get(ACTIVE).attributes["end"] == "15:00"
    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    assert hass.states.get(ACTIVE).state == "off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    assert hass.states.get(ACTIVE).state == "on"
    # the new end is scheduled, the old 07:00 boundary no longer matters
    freezer.move_to(local(15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(ACTIVE).state == "off"


async def test_settings_survive_a_reload(hass: HomeAssistant, freezer):
    freezer.move_to(local(14))
    entry = await setup(hass)
    await set_time(hass, START, "21:30:00")
    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(START).state == "21:30:00"
    assert hass.states.get(SWITCH).state == "off"


async def test_unload_cancels_the_timer(hass: HomeAssistant, freezer):
    freezer.move_to(local(14))
    entry = await setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.move_to(local(20))
    async_fire_time_changed(hass)                                        # nothing may fire into an unloaded entity
    await hass.async_block_till_done()

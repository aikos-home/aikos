"""binary_sensor.aikos_front_door in a real Home Assistant test instance: debounce, availability, stuck, source change."""
from datetime import timedelta

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

DOMAIN = "aikos"
DOOR = "binary_sensor.aikos_front_door"
SRC, SRC2 = "binary_sensor.aikos_door_contact", "input_boolean.aikos_test_front_door"


async def setup(hass: HomeAssistant, source=SRC):
    hass.states.async_set(SRC, "off")
    hass.states.async_set(SRC2, "off")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    entry = result["result"]
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {"front_door": source} if source else {})
    await hass.async_block_till_done()
    return entry


async def later(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_opens_and_closes_after_2_s(hass: HomeAssistant, freezer):
    await setup(hass)
    assert hass.states.get(DOOR).state == "off" and hass.states.get(DOOR).attributes["source"] == SRC
    hass.states.async_set(SRC, "on")
    await later(hass, freezer, 1)
    assert hass.states.get(DOOR).state == "off"                      # not yet
    await later(hass, freezer, 1.5)
    assert hass.states.get(DOOR).state == "on"
    hass.states.async_set(SRC, "off")
    await later(hass, freezer, 2.5)
    assert hass.states.get(DOOR).state == "off"


async def test_a_blip_shorter_than_2_s_is_ignored(hass: HomeAssistant, freezer):
    await setup(hass)
    hass.states.async_set(SRC, "on")
    await later(hass, freezer, 1)
    hass.states.async_set(SRC, "off")
    await later(hass, freezer, 3)
    assert hass.states.get(DOOR).state == "off"


async def test_unavailable_when_the_source_is(hass: HomeAssistant, freezer):
    await setup(hass)
    hass.states.async_set(SRC, "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(DOOR).state == "unavailable"
    hass.states.async_set(SRC, "off")
    await hass.async_block_till_done()
    assert hass.states.get(DOOR).state == "off"


async def test_no_source_configured_is_unavailable(hass: HomeAssistant):
    await setup(hass, source=None)
    assert hass.states.get(DOOR).state == "unavailable"


async def test_stuck_after_10_minutes_open(hass: HomeAssistant, freezer):
    await setup(hass)
    hass.states.async_set(SRC, "on")
    await later(hass, freezer, 2.5)
    assert hass.states.get(DOOR).attributes["stuck"] is False
    await later(hass, freezer, 601)
    assert hass.states.get(DOOR).state == "on" and hass.states.get(DOOR).attributes["stuck"] is True
    hass.states.async_set(SRC, "off")
    await later(hass, freezer, 2.5)
    assert hass.states.get(DOOR).attributes["stuck"] is False


async def test_changing_the_source_in_the_options(hass: HomeAssistant, freezer):
    entry = await setup(hass)
    hass.states.async_set(SRC2, "on")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {"front_door": SRC2})
    await hass.async_block_till_done()
    door = hass.states.get(DOOR)
    assert door.attributes["source"] == SRC2 and door.state == "on"    # a new source counts as it is
    assert dt_util.utcnow()                                              # (freezer active)

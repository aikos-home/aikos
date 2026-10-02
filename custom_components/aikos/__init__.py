"""aikos: the house system's Home Assistant integration (quiet hours first; more blocks follow)."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .settings import QuietHoursSettings

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SWITCH, Platform.TIME]


@dataclass
class AikosData:
    version: str
    quiet_hours: QuietHoursSettings


type AikosConfigEntry = ConfigEntry[AikosData]


async def async_setup_entry(hass: HomeAssistant, entry: AikosConfigEntry) -> bool:
    integration = await async_get_integration(hass, DOMAIN)
    entry.runtime_data = AikosData(version=str(integration.version), quiet_hours=QuietHoursSettings(hass, entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AikosConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

"""aikos: the house system's Home Assistant integration (quiet hours, ring push, call log, call archive; more blocks follow)."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .archive_writer import ArchiveWriter
from .const import DOMAIN
from .ring_notifier import RingNotifier
from .settings import QuietHoursSettings

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH, Platform.TIME]


@dataclass
class AikosData:
    version: str
    quiet_hours: QuietHoursSettings
    ring_notifier: RingNotifier
    archive: ArchiveWriter


type AikosConfigEntry = ConfigEntry[AikosData]


async def async_setup_entry(hass: HomeAssistant, entry: AikosConfigEntry) -> bool:
    integration = await async_get_integration(hass, DOMAIN)
    quiet_hours = QuietHoursSettings(hass, entry)
    notifier = RingNotifier(hass, entry, quiet_hours)
    archive = ArchiveWriter(hass, entry)
    entry.runtime_data = AikosData(version=str(integration.version), quiet_hours=quiet_hours, ring_notifier=notifier,
                                   archive=archive)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    notifier.start()
    entry.async_on_unload(notifier.stop)
    archive.start()
    entry.async_on_unload(archive.stop)
    # Options change (doorbell picked, or a quiet-hours value stored): follow the doorbell without reloading the entities.
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass: HomeAssistant, entry: AikosConfigEntry) -> None:
    entry.runtime_data.ring_notifier.start()
    entry.runtime_data.archive.start()


async def async_unload_entry(hass: HomeAssistant, entry: AikosConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

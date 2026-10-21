"""aikos: the house system's Home Assistant integration (quiet hours, ring push, call log, call archive, door messages; more
blocks follow)."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .archive_writer import ArchiveWriter
from .const import DOMAIN
from .message_register import DoorMessageRegister
from .ring_notifier import RingNotifier
from .services import async_setup_services
from .settings import QuietHoursSettings

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH, Platform.TIME]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class AikosData:
    version: str
    quiet_hours: QuietHoursSettings
    ring_notifier: RingNotifier
    archive: ArchiveWriter
    door_messages: DoorMessageRegister


type AikosConfigEntry = ConfigEntry[AikosData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AikosConfigEntry) -> bool:
    integration = await async_get_integration(hass, DOMAIN)
    quiet_hours = QuietHoursSettings(hass, entry)
    notifier = RingNotifier(hass, entry, quiet_hours)
    archive = ArchiveWriter(hass, entry)
    door_messages = DoorMessageRegister(hass, entry)
    await door_messages.async_load()
    entry.runtime_data = AikosData(version=str(integration.version), quiet_hours=quiet_hours, ring_notifier=notifier,
                                   archive=archive, door_messages=door_messages)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    notifier.start()
    entry.async_on_unload(notifier.stop)
    archive.start()
    entry.async_on_unload(archive.stop)
    door_messages.start()
    entry.async_on_unload(door_messages.stop)
    # Options change (doorbell picked, or a quiet-hours value stored): follow the doorbell without reloading the entities.
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass: HomeAssistant, entry: AikosConfigEntry) -> None:
    entry.runtime_data.ring_notifier.start()
    entry.runtime_data.archive.start()


async def async_unload_entry(hass: HomeAssistant, entry: AikosConfigEntry) -> bool:
    entry.runtime_data.door_messages.stop()
    await entry.runtime_data.door_messages.async_flush()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

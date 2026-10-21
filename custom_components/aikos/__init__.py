"""aikos: the house system's Home Assistant integration (quiet hours, ring push, call log, call archive, door messages, door
actions, door announcements; more blocks follow)."""
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
from .door_actions import DoorActions
from .door_announce import DoorAnnouncer
from .door_speech import DoorSpeech
from .message_register import DoorMessageRegister
from .ring_notifier import RingNotifier
from .services import async_setup_services
from .settings import QuietHoursSettings

PLATFORMS = [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH, Platform.TIME]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class AikosData:
    version: str
    quiet_hours: QuietHoursSettings
    ring_notifier: RingNotifier
    archive: ArchiveWriter
    door_messages: DoorMessageRegister
    door_actions: DoorActions
    door_announcer: DoorAnnouncer


type AikosConfigEntry = ConfigEntry[AikosData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AikosConfigEntry) -> bool:
    integration = await async_get_integration(hass, DOMAIN)
    quiet_hours = QuietHoursSettings(hass, entry)
    speech = DoorSpeech(hass, entry)
    door_actions = DoorActions(hass, entry, speech)
    await door_actions.async_load()
    announcer = DoorAnnouncer(hass, entry, speech, quiet_hours, muted=lambda: door_actions.muted)
    await announcer.async_load()
    door_actions.approach = announcer.on_approach
    notifier = RingNotifier(hass, entry, quiet_hours, muted=lambda: door_actions.muted)
    archive = ArchiveWriter(hass, entry)
    door_messages = DoorMessageRegister(hass, entry)
    await door_messages.async_load()
    entry.runtime_data = AikosData(version=str(integration.version), quiet_hours=quiet_hours, ring_notifier=notifier,
                                   archive=archive, door_messages=door_messages, door_actions=door_actions,
                                   door_announcer=announcer)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    notifier.start()
    entry.async_on_unload(notifier.stop)
    archive.start()
    entry.async_on_unload(archive.stop)
    door_messages.start()
    entry.async_on_unload(door_messages.stop)
    door_actions.start()
    entry.async_on_unload(door_actions.stop)
    announcer.start()
    entry.async_on_unload(announcer.stop)
    # Options change (doorbell picked, or a quiet-hours value stored): follow the doorbell without reloading the entities.
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass: HomeAssistant, entry: AikosConfigEntry) -> None:
    entry.runtime_data.ring_notifier.start()
    entry.runtime_data.archive.start()
    entry.runtime_data.door_announcer.start()


async def async_unload_entry(hass: HomeAssistant, entry: AikosConfigEntry) -> bool:
    entry.runtime_data.door_messages.stop()
    await entry.runtime_data.door_messages.async_flush()
    entry.runtime_data.door_actions.stop()
    await entry.runtime_data.door_actions.async_flush()
    entry.runtime_data.door_announcer.stop()
    await entry.runtime_data.door_announcer.async_flush()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

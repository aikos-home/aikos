"""The household's quiet-hours settings: kept in the config entry's options, so they survive restarts and backups."""
from __future__ import annotations

from collections.abc import Callable
from datetime import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    DEFAULT_QUIET_ENABLED,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    OPT_QUIET_ENABLED,
    OPT_QUIET_END,
    OPT_QUIET_START,
)


def _parse_time(value: str | None, default: time) -> time:
    try:
        return time.fromisoformat(value) if value else default
    except ValueError:
        return default


class QuietHoursSettings:
    """On/off, start and end of the quiet hours. Entities read and change them here; listeners hear every change."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._listeners: list[Callable[[], None]] = []

    @property
    def enabled(self) -> bool:
        return bool(self._entry.options.get(OPT_QUIET_ENABLED, DEFAULT_QUIET_ENABLED))

    @property
    def start(self) -> time:
        return _parse_time(self._entry.options.get(OPT_QUIET_START), DEFAULT_QUIET_START)

    @property
    def end(self) -> time:
        return _parse_time(self._entry.options.get(OPT_QUIET_END), DEFAULT_QUIET_END)

    @callback
    def update(self, *, enabled: bool | None = None, start: time | None = None, end: time | None = None) -> None:
        options = dict(self._entry.options)
        if enabled is not None:
            options[OPT_QUIET_ENABLED] = enabled
        if start is not None:
            options[OPT_QUIET_START] = start.isoformat()
        if end is not None:
            options[OPT_QUIET_END] = end.isoformat()
        self._hass.config_entries.async_update_entry(self._entry, options=options)
        for listener in list(self._listeners):
            listener()

    @callback
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            self._listeners.remove(listener)

        return remove

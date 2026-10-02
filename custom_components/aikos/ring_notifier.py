"""Watches the doorbell and sends the push (quiet hours or nobody home) to the configured notify services."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import OPT_DOORBELL, OPT_NOTIFY, OPT_RESIDENTS
from .quiet_hours import is_quiet
from .ring_push import push_message, push_reason
from .settings import QuietHoursSettings

_LOGGER = logging.getLogger(__name__)


def is_ring(old: State | None, new: State | None) -> bool:
    """A press of the doorbell: an event entity got a new timestamp, or a binary sensor went off → on.

    A device coming back (unavailable → its last timestamp) is no press.
    """
    if old is None or new is None or old.state in (STATE_UNAVAILABLE,) or new.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return False
    if new.domain == "binary_sensor":
        return old.state != STATE_ON and new.state == STATE_ON
    return new.state != old.state


class RingNotifier:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, quiet_hours: QuietHoursSettings) -> None:
        self._hass = hass
        self._entry = entry
        self._quiet = quiet_hours
        self._last_push: datetime | None = None
        self._unsub: Callable[[], None] | None = None
        self._doorbell: str | None = None

    @callback
    def start(self) -> None:
        """(Re)subscribe to the doorbell from the current options."""
        doorbell = self._entry.options.get(OPT_DOORBELL)
        if doorbell == self._doorbell and self._unsub is not None:
            return
        self.stop()
        self._doorbell = doorbell
        if doorbell:
            self._unsub = async_track_state_change_event(self._hass, [doorbell], self._on_change)

    @callback
    def stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback
    def _on_change(self, event: Event[EventStateChangedData]) -> None:
        if not is_ring(event.data["old_state"], event.data["new_state"]):
            return
        now = dt_util.now()
        q = self._quiet
        quiet_active = q.enabled and is_quiet(now.time(), q.start, q.end)
        residents = [self._hass.states.get(p) for p in self._entry.options.get(OPT_RESIDENTS, [])]
        states = [s.state if s else STATE_UNKNOWN for s in residents]
        reason = push_reason(quiet_active, states, self._last_push, now)
        if reason is None:
            return
        self._last_push = now
        message = push_message(reason, now, self._hass.config.language)
        for target in self._entry.options.get(OPT_NOTIFY, []):
            service = target.removeprefix("notify.")
            if not self._hass.services.has_service("notify", service):
                _LOGGER.warning("aikos: notify service notify.%s not found, ring push not sent there", service)
                continue
            self._hass.async_create_task(self._send(service, message))
        _LOGGER.info("aikos: ring pushed (%s)", reason)

    async def _send(self, service: str, message: str) -> None:
        try:
            await self._hass.services.async_call("notify", service, {"title": "aikos", "message": message}, blocking=True)
        except Exception:  # a broken phone target must never stop the others or the integration
            _LOGGER.exception("aikos: ring push via notify.%s failed", service)

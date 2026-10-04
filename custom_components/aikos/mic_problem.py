"""`binary_sensor.aikos_mic_problem` (and its bench twin `_test`): on while a device's mic is broken (W3).

Fed by the transcriber's event `aikos_mic_check` (`aikos_mic_check_test` for the twin). For the live sensor a new problem also
creates a persistent notification and a push to the configured phones; recovery dismisses the notification.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import Event, callback
from homeassistant.util import dt as dt_util

from .const import OPT_NOTIFY
from .entity import AikosEntity
from .mic_health import CLEARED, PROBLEM, MicHealth, message

_LOGGER = logging.getLogger(__name__)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "unknown"


class MicProblem(AikosEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry, key: str, entity_id: str, event_type: str, announce: bool) -> None:
        super().__init__(entry, key, entity_id)
        self._event_type = event_type
        self._announce = announce                  # live sensor only: notification + push
        self._health = MicHealth()

    @property
    def is_on(self) -> bool:
        return bool(self._health.problem_devices)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "problem_devices": self._health.problem_devices,
            "devices": {name: {"verdict": d.verdict, "bad_in_a_row": d.bad_in_a_row, "problem": d.problem, "since": d.since,
                               **{k: d.last.get(k) for k in ("peak_db", "rms_db", "zero_ratio", "clip_ratio", "duration_s")}}
                        for name, d in self._health.devices.items()},
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hass.bus.async_listen(self._event_type, self._on_check))

    @callback
    def _on_check(self, event: Event) -> None:
        data = event.data
        device = str(data.get("device") or data.get("source") or "unknown")
        verdict = str(data.get("verdict") or "")
        if not verdict:
            return
        change = self._health.note(device, verdict, dt_util.now().isoformat(timespec="seconds"), dict(data))
        self.async_write_ha_state()
        if self._announce and change:
            self.hass.async_create_task(self._tell(device, verdict, change))

    async def _tell(self, device: str, verdict: str, change: str) -> None:
        notification_id = f"aikos_mic_{_slug(device)}"
        try:
            if change == CLEARED:
                if self.hass.services.has_service("persistent_notification", "dismiss"):
                    await self.hass.services.async_call("persistent_notification", "dismiss",
                                                        {"notification_id": notification_id}, blocking=True)
                return
            title, text = message(device, verdict, self.hass.config.language)
            if change == PROBLEM and self.hass.services.has_service("persistent_notification", "create"):
                await self.hass.services.async_call("persistent_notification", "create",
                                                    {"notification_id": notification_id, "title": title, "message": text},
                                                    blocking=True)
            for target in self._entry.options.get(OPT_NOTIFY, []):
                service = target.removeprefix("notify.")
                if self.hass.services.has_service("notify", service):
                    await self.hass.services.async_call("notify", service, {"title": title, "message": text}, blocking=True)
        except Exception:  # a warning must never break the integration
            _LOGGER.exception("aikos: mic warning for %s failed", device)

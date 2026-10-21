"""The door actions' entities: `binary_sensor.aikos_bell_muted` (the door contract), `switch.aikos_bell_mute`,
`sensor.aikos_door_note`, `sensor.aikos_door_greeting`, `sensor.aikos_door_picture`. They show the state of door_actions.py."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.util import dt as dt_util

from .door_actions import DoorActions
from .entity import AikosEntity


class _DoorEntity(AikosEntity):
    @property
    def door(self) -> DoorActions:
        return self._entry.runtime_data.door_actions

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.door.add_listener(self.async_write_ha_state))


class BellMuted(_DoorEntity, BinarySensorEntity):
    """On while the bell is muted (A14/A40). The door screen reads it and behaves as in quiet hours."""

    @property
    def is_on(self) -> bool:
        return self.door.muted

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        m = self.door.state.mute
        return {"until": m.until if self.door.muted else ""}


class BellMuteSwitch(_DoorEntity, SwitchEntity):
    """On = muted until switched off; for a time: service aikos.bell_mute."""

    @property
    def is_on(self) -> bool:
        return self.door.muted

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.door.mute(forever=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.door.unmute()


class DoorNote(_DoorEntity, SensorEntity):
    """`waiting` while a note waits for the next visitor (A39), else `none`."""

    @property
    def native_value(self) -> str:
        return "waiting" if self.door.state.note else "none"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        n = self.door.state.note
        return {"message": n.message if n else "", "sender": n.sender if n else "", "since": n.since if n else ""}


class DoorGreeting(_DoorEntity, SensorEntity):
    """`active` (shown and played now), `scheduled` (window still ahead), `off`."""

    @property
    def native_value(self) -> str:
        g = self.door.state.greeting
        if g.in_window(dt_util.now()):
            return "active"
        return "scheduled" if g.enabled and g.next_change(dt_util.now()) is not None else "off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        g = self.door.state.greeting
        return {"enabled": g.enabled, "text": g.text, "start": g.start, "end": g.end, "audio": bool(g.audio),
                "audio_file": g.audio, "last_played": g.last_played}


class DoorPicture(_DoorEntity, SensorEntity):
    """`shown` while a picture is on the door's welcome page (A12/A41), else `none`; `path` under /local."""

    @property
    def native_value(self) -> str:
        return "shown" if self.door.state.picture else "none"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"path": self.door.picture_path()}

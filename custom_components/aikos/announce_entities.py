"""The door announcements' entities (sprachausgabe S3, S10–S14): `number.aikos_door_disclosure`, the slider 0–4 of what the
door may tell, and `sensor.aikos_door_announcements`: what a ring would get now (`parcel`, `away`, `quiet`, `none`) and, in
its attributes, the sentences, released places and residents, the zones and residents to choose from, and the last
announcement. They show the state of door_announce.py."""
from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.sensor import SensorEntity

from .announce_rules import LEVEL_MAX, SITUATIONS
from .const import OPT_RESIDENTS
from .door_announce import DoorAnnouncer
from .entity import AikosEntity


class _AnnounceEntity(AikosEntity):
    @property
    def announcer(self) -> DoorAnnouncer:
        return self._entry.runtime_data.door_announcer

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.announcer.add_listener(self.async_write_ha_state))


class Disclosure(_AnnounceEntity, NumberEntity):
    """0 = the door tells nothing … 4 = also where the residents are (only those who agreed, only released places)."""

    _attr_native_min_value = 0
    _attr_native_max_value = LEVEL_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> float:
        return self.announcer.state.disclosure

    async def async_set_native_value(self, value: float) -> None:
        await self.announcer.async_set(disclosure=int(value))


class DoorAnnouncements(_AnnounceEntity, SensorEntity):
    @property
    def native_value(self) -> str:
        now = self.announcer.now()
        return "+".join(s for s, _ in now) or "none"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        a, hass = self.announcer.state, self.hass
        now = self.announcer.now()
        zones = [{"id": z.entity_id, "name": z.name} for z in hass.states.async_all("zone") if z.object_id != "home"]
        residents = []
        for person in self._entry.options.get(OPT_RESIDENTS, []):
            st = hass.states.get(person)
            residents.append({"id": person, "name": st.name if st else person})
        return {"disclosure": a.disclosure, **{s: a.texts.get(s, "") for s in SITUATIONS}, "away_places": a.away_places,
                "places": dict(a.places), "named": list(a.named), "voice": bool(a.voice),
                "now_text": " ".join(t for _, t in now),
                "ready": sorted(self.announcer.ready), "last": dict(self.announcer.last), "zones": zones,
                "residents": residents}

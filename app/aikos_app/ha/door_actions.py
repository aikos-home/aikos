"""Door actions through the aikos integration (aikos 0.9.0+; rules A11–A14, A39–A41): bell mute, quiet hours, a note to
the door, the door picture, the greeting. Each is exactly one aikos service; the entity ids are the integration's fixed ids
(the same in every house). The caller has checked the person's rights.
"""

from __future__ import annotations

import base64
from typing import Any

from .client import HaClient, HaError

QUICK_REPLIES = ("Komme sofort.", "Bitte vor die Tür legen.", "Moment bitte.")
"""The quick replies of "An die Tür sagen" (one list for the app and for the speech made in advance)."""
NOTE = "sensor.aikos_door_note"
GREETING = "sensor.aikos_door_greeting"
PICTURE = "sensor.aikos_door_picture"
ENTITIES = (NOTE, GREETING, PICTURE)
PICTURE_PREFIX = "/local/aikos_door/"
GREETING_FOLDER = "media-source://media_source/local/aikos"


class NoDoorActions(HaError):
    """The integration is older than 0.9.0 (no door actions)."""


def _attrs(ha: HaClient, entity_id: str) -> dict[str, Any]:
    return dict((ha.state(entity_id) or {}).get("attributes") or {})


def actions_state(ha: HaClient) -> dict[str, Any] | None:
    """What the app shows of the door actions; None without aikos 0.9.0."""
    if ha.state(NOTE) is None:
        return None
    note = _attrs(ha, NOTE)
    g = _attrs(ha, GREETING)
    pic = _attrs(ha, PICTURE)
    return {
        "note": {"message": note.get("message", ""), "sender": note.get("sender", ""), "since": note.get("since", "")}
        if (ha.state(NOTE) or {}).get("state") == "waiting" else None,
        "greeting": {"state": (ha.state(GREETING) or {}).get("state") or "off", "enabled": bool(g.get("enabled")),
                     "text": g.get("text") or "", "start": g.get("start") or "", "end": g.get("end") or "",
                     "audio": bool(g.get("audio"))},
        "picture": bool(pic.get("path")),
        "quick": list(QUICK_REPLIES),
    }


class DoorActions:
    def __init__(self, ha: HaClient) -> None:
        self.ha = ha

    def _need(self) -> None:
        if self.ha.state(NOTE) is None:
            raise NoDoorActions("no door actions")

    async def _call(self, service: str, data: dict[str, Any] | None = None, response: bool = False) -> Any:
        self._need()
        return await self.ha.call_service("aikos", service, data or {}, response=response)

    # bell (A14/A40) and quiet hours
    async def mute(self, *, minutes: int | None = None, until_time: str = "", forever: bool = False) -> None:
        data: dict[str, Any] = {"forever": True} if forever else {"minutes": minutes} if minutes else {"until_time": until_time}
        await self._call("bell_mute", data)

    async def unmute(self) -> None:
        await self._call("bell_unmute")

    async def quiet_hours(self, data: dict[str, Any]) -> None:
        await self._call("quiet_hours", data)

    # a note to the door (A11/A39)
    async def say(self, message: str, sender: str, voice: str = "") -> str:
        """`voice` = the sender's own voice (read aloud in it); "" = shown only (A45)."""
        res = await self._call("door_say", {"message": message, "sender": sender, "voice": voice}, response=True)
        return str((res or {}).get("delivered") or "")

    async def cancel_note(self) -> None:
        await self._call("door_say_cancel", response=True)

    # the door picture (A12/A41)
    async def set_picture(self, image: bytes) -> None:
        await self._call("door_picture", {"image": base64.b64encode(image).decode("ascii")}, response=True)

    async def clear_picture(self) -> None:
        await self._call("door_picture_clear")

    def picture_path(self) -> str:
        path = str(_attrs(self.ha, PICTURE).get("path") or "")
        return path if path.startswith(PICTURE_PREFIX) and ".." not in path else ""

    # the greeting (A13/A26)
    async def set_greeting(self, data: dict[str, Any]) -> None:
        await self._call("door_greeting", data, response=True)

    async def set_greeting_audio(self, audio: bytes) -> None:
        await self._call("door_greeting", {"audio": base64.b64encode(audio).decode("ascii")}, response=True)

    async def clear_greeting_audio(self) -> None:
        await self._call("door_greeting", {"clear_audio": True}, response=True)

    async def greeting_audio_link(self) -> str:
        name = str(_attrs(self.ha, GREETING).get("audio_file") or "")
        if not name or "/" in name or ".." in name:
            return ""
        res = await self.ha.command("media_source/resolve_media", media_content_id=f"{GREETING_FOLDER}/{name}")
        return str(res.get("url") or "")

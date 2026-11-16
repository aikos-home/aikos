"""The services for the aikos app (no admin rights needed to call them). Who may do what is the app's decision.

Door message register: `aikos.door_messages` returns the list; `aikos.door_message_delete` deletes a message and its MP3;
`aikos.door_message_heard` notes who heard it (A15, A38); `by` is the resident's name for the record.
Door actions (A11–A14, A39–A41): bell mute, quiet hours, a note to the door, the door picture, the greeting.
Door announcements (sprachausgabe S10–S14): `aikos.door_announcements` sets the sentences, the disclosure level, the places
that may be named and who agreed to it; only the fields given change.
"""
from __future__ import annotations

import base64
import binascii
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .announce_rules import LEVEL_MAX, PLACE_MAX, PLACES_MAX, SITUATIONS, TEXT_MAX
from .const import DOMAIN
from .door_actions import DoorActions
from .door_announce import DoorAnnouncer
from .door_picture import PictureError
from .door_rules import GREETING_MAX, MUTE_MAX_MINUTES, NOTE_MAX, SENDER_MAX
from .message_register import DoorMessageRegister

LIST, DELETE, HEARD = "door_messages", "door_message_delete", "door_message_heard"
_ONE = vol.Schema({vol.Required("id"): cv.string, vol.Optional("by", default=""): vol.All(cv.string, vol.Length(max=60))})
_HEARD = vol.Schema({vol.Required("id"): cv.string, vol.Required("by"): vol.All(cv.string, vol.Length(min=1, max=60))})


def _loaded(hass: HomeAssistant) -> Any:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    raise ServiceValidationError("aikos is not set up", translation_domain=DOMAIN, translation_key="not_loaded")


def _register(hass: HomeAssistant) -> DoorMessageRegister:
    return _loaded(hass).door_messages


def _door(hass: HomeAssistant) -> DoorActions:
    return _loaded(hass).door_actions


def _announcer(hass: HomeAssistant) -> DoorAnnouncer:
    return _loaded(hass).door_announcer


def _invalid(reason: str) -> ServiceValidationError:
    return ServiceValidationError(reason, translation_domain=DOMAIN, translation_key="invalid",
                                  translation_placeholders={"reason": reason})


def _b64(text: str, limit: int) -> bytes:
    if len(text) > limit * 4 // 3 + 8:
        raise _invalid("file too large")
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise _invalid("not base64") from None


def _unknown(msg_id: str) -> ServiceValidationError:
    return ServiceValidationError(f"no door message {msg_id!r}", translation_domain=DOMAIN, translation_key="unknown_message",
                                  translation_placeholders={"id": msg_id})


async def _list(call: ServiceCall) -> ServiceResponse:
    return {"messages": await _register(call.hass).async_list()}


async def _delete(call: ServiceCall) -> ServiceResponse:
    m = await _register(call.hass).async_delete(call.data["id"], call.data["by"])
    if m is None:
        raise _unknown(call.data["id"])
    return {"deleted": m.id}


async def _heard(call: ServiceCall) -> None:
    if await _register(call.hass).async_heard(call.data["id"], call.data["by"]) is None:
        raise _unknown(call.data["id"])


_MUTE = vol.Schema({vol.Exclusive("minutes", "how"): vol.All(vol.Coerce(int), vol.Range(min=1, max=MUTE_MAX_MINUTES)),
                    vol.Exclusive("until_time", "how"): cv.time, vol.Exclusive("forever", "how"): cv.boolean})
_QUIET = vol.Schema({vol.Optional("enabled"): cv.boolean, vol.Optional("start"): cv.time, vol.Optional("end"): cv.time})
_VOICE = vol.All(cv.string, vol.Match(r"^$|^[a-z0-9][a-z0-9_-]{0,39}$"))
_SAY = vol.Schema({vol.Required("message"): vol.All(cv.string, vol.Length(min=1, max=NOTE_MAX)),
                   vol.Optional("sender", default=""): vol.All(cv.string, vol.Length(max=SENDER_MAX)),
                   vol.Optional("voice", default=""): _VOICE})
_PICTURE = vol.Schema({vol.Required("image"): cv.string})
_IPV4 = vol.All(cv.string, vol.Match(r"^\d{1,3}(\.\d{1,3}){3}$"))
_APP_TALKER = vol.Schema({vol.Optional("ip", default=""): vol.Any("", _IPV4),
                          vol.Optional("name", default=""): vol.All(cv.string, vol.Length(max=SENDER_MAX))})
_SAY_AUDIO = vol.Schema({vol.Required("audio"): cv.string,
                         vol.Optional("sender", default=""): vol.All(cv.string, vol.Length(max=SENDER_MAX)),
                         vol.Optional("seconds"): vol.All(vol.Coerce(float), vol.Range(min=0, max=120))})
_GREETING = vol.Schema({vol.Optional("enabled"): cv.boolean,
                        vol.Optional("text"): vol.All(cv.string, vol.Length(max=GREETING_MAX)),
                        vol.Optional("start"): cv.datetime, vol.Optional("end"): cv.datetime,
                        vol.Optional("clear_window", default=False): cv.boolean,
                        vol.Optional("audio"): cv.string, vol.Optional("clear_audio", default=False): cv.boolean,
                        vol.Optional("voice"): _VOICE})
_SENTENCE = vol.All(cv.string, vol.Length(max=TEXT_MAX))
_ANNOUNCE = vol.Schema({vol.Optional("disclosure"): vol.All(vol.Coerce(int), vol.Range(min=0, max=LEVEL_MAX)),
                        **{vol.Optional(s): _SENTENCE for s in SITUATIONS},
                        vol.Optional("away_places"): _SENTENCE,
                        vol.Optional("places"): vol.All(
                            {vol.Match(r"^zone\.[a-z0-9_]+$"): vol.All(cv.string, vol.Length(max=PLACE_MAX))},
                            vol.Length(max=PLACES_MAX)),
                        vol.Optional("named"): vol.All(cv.ensure_list, [vol.Match(r"^person\.[a-z0-9_]+$")]),
                        vol.Optional("voice"): _VOICE})


async def _mute(call: ServiceCall) -> None:
    d = call.data
    if not any(k in d for k in ("minutes", "until_time", "forever")) or d.get("forever") is False:
        raise _invalid("minutes, until_time or forever")
    _door(call.hass).mute(minutes=d.get("minutes"), until_time=d.get("until_time"), forever=bool(d.get("forever")))


async def _unmute(call: ServiceCall) -> None:
    _door(call.hass).unmute()


async def _quiet(call: ServiceCall) -> None:
    _loaded(call.hass).quiet_hours.update(enabled=call.data.get("enabled"), start=call.data.get("start"),
                                          end=call.data.get("end"))


async def _say(call: ServiceCall) -> ServiceResponse:
    try:
        return {"delivered": await _door(call.hass).async_say(call.data["message"], call.data["sender"],
                                                               call.data["voice"])}
    except ValueError as e:
        raise _invalid(str(e)) from None


async def _say_audio(call: ServiceCall) -> ServiceResponse:
    d = call.data
    try:
        return {"delivered": await _door(call.hass).async_say_audio(_b64(d["audio"], 3 * 1024 * 1024), d["sender"],
                                                                    d.get("seconds"))}
    except ValueError as e:
        raise _invalid(str(e)) from None


async def _app_talker(call: ServiceCall) -> None:
    _loaded(call.hass).app_talker.set(call.data["ip"], call.data["name"])


async def _say_cancel(call: ServiceCall) -> ServiceResponse:
    return {"cancelled": await _door(call.hass).async_cancel_note()}


async def _picture(call: ServiceCall) -> ServiceResponse:
    try:
        return {"path": await _door(call.hass).async_set_picture(_b64(call.data["image"], 8 * 1024 * 1024))}
    except PictureError as e:
        raise _invalid(str(e)) from None


async def _picture_clear(call: ServiceCall) -> None:
    await _door(call.hass).async_clear_picture()


async def _greeting(call: ServiceCall) -> ServiceResponse:
    d = call.data
    try:
        g = await _door(call.hass).async_set_greeting(
            enabled=d.get("enabled"), text=d.get("text"), start=d.get("start"), end=d.get("end"),
            clear_window=d["clear_window"], audio=_b64(d["audio"], 3 * 1024 * 1024) if "audio" in d else None,
            clear_audio=d["clear_audio"], voice=d.get("voice"))
    except ValueError as e:
        raise _invalid(str(e)) from None
    return {"enabled": g.enabled, "text": g.text, "start": g.start, "end": g.end, "audio": bool(g.audio)}


async def _announcements(call: ServiceCall) -> ServiceResponse:
    d = call.data
    texts = {s: d[s] for s in SITUATIONS if s in d}
    try:
        a = await _announcer(call.hass).async_set(disclosure=d.get("disclosure"), texts=texts or None,
                                                  away_places=d.get("away_places"), places=d.get("places"),
                                                  named=d.get("named"), voice=d.get("voice"))
    except ValueError as e:
        raise _invalid(str(e)) from None
    return {**a.to_dict(), "voice": bool(a.voice)}


def async_setup_services(hass: HomeAssistant) -> None:
    hass.services.async_register(DOMAIN, LIST, _list, schema=vol.Schema({}), supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, DELETE, _delete, schema=_ONE, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, HEARD, _heard, schema=_HEARD)
    reg = hass.services.async_register
    reg(DOMAIN, "bell_mute", _mute, schema=_MUTE)
    reg(DOMAIN, "bell_unmute", _unmute, schema=vol.Schema({}))
    reg(DOMAIN, "quiet_hours", _quiet, schema=_QUIET)
    reg(DOMAIN, "door_say", _say, schema=_SAY, supports_response=SupportsResponse.OPTIONAL)
    reg(DOMAIN, "door_say_cancel", _say_cancel, schema=vol.Schema({}), supports_response=SupportsResponse.OPTIONAL)
    reg(DOMAIN, "door_say_audio", _say_audio, schema=_SAY_AUDIO, supports_response=SupportsResponse.OPTIONAL)
    reg(DOMAIN, "app_talker", _app_talker, schema=_APP_TALKER)
    reg(DOMAIN, "door_picture", _picture, schema=_PICTURE, supports_response=SupportsResponse.OPTIONAL)
    reg(DOMAIN, "door_picture_clear", _picture_clear, schema=vol.Schema({}))
    reg(DOMAIN, "door_greeting", _greeting, schema=_GREETING, supports_response=SupportsResponse.OPTIONAL)
    reg(DOMAIN, "door_announcements", _announcements, schema=_ANNOUNCE, supports_response=SupportsResponse.OPTIONAL)

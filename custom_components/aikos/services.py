"""The services of the door message register, for the aikos app (no admin rights needed to call them).

`aikos.door_messages` returns the list; `aikos.door_message_delete` deletes a message and its MP3; `aikos.door_message_heard`
notes who heard it. Who may do what is the app's decision (A15, A38); `by` is the resident's name for the record.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .message_register import DoorMessageRegister

LIST, DELETE, HEARD = "door_messages", "door_message_delete", "door_message_heard"
_ONE = vol.Schema({vol.Required("id"): cv.string, vol.Optional("by", default=""): vol.All(cv.string, vol.Length(max=60))})
_HEARD = vol.Schema({vol.Required("id"): cv.string, vol.Required("by"): vol.All(cv.string, vol.Length(min=1, max=60))})


def _register(hass: HomeAssistant) -> DoorMessageRegister:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data.door_messages
    raise ServiceValidationError("aikos is not set up", translation_domain=DOMAIN, translation_key="not_loaded")


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


def async_setup_services(hass: HomeAssistant) -> None:
    hass.services.async_register(DOMAIN, LIST, _list, schema=vol.Schema({}), supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, DELETE, _delete, schema=_ONE, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, HEARD, _heard, schema=_HEARD)

"""Setting up aikos (one click) and its options: doorbell, residents and their phones for the ring push; the front door
sensor; the call archive; the voice service that reads at the door; the parcel sensor for the door announcements; the
mailbox whose carrier mails tell whether a parcel comes today (its login is tried before it is stored).

Daily settings such as quiet hours are entities of the "aikos" device, not options.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import parcel_mail
from .const import (
    DOMAIN,
    OPT_ARCHIVE,
    OPT_DOORBELL,
    OPT_FRONT_DOOR,
    OPT_MAIL_PASSWORD,
    OPT_MAIL_SERVER,
    OPT_MAIL_USER,
    OPT_NOTIFY,
    OPT_PARCEL,
    OPT_RESIDENTS,
    OPT_TTS,
)

ENTITY_OPTIONS = (OPT_DOORBELL, OPT_RESIDENTS, OPT_NOTIFY, OPT_FRONT_DOOR, OPT_TTS, OPT_PARCEL)


class AikosConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="aikos", data={})
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AikosOptionsFlow()


class AikosOptionsFlow(OptionsFlow):
    async def _mail(self, user_input: dict[str, Any], options: dict[str, Any]) -> str:
        """Takes the parcel mailbox into `options`; returns an error key, "" if fine. An empty user turns it off; an empty
        password keeps the stored one for the same mailbox."""
        user = (user_input.get(OPT_MAIL_USER) or "").strip()
        if not user:
            for key in (OPT_MAIL_SERVER, OPT_MAIL_USER, OPT_MAIL_PASSWORD):
                options.pop(key, None)
            return ""
        server = (user_input.get(OPT_MAIL_SERVER) or parcel_mail.DEFAULT_SERVER).strip()
        same = user == options.get(OPT_MAIL_USER) and server == options.get(OPT_MAIL_SERVER, parcel_mail.DEFAULT_SERVER)
        password = user_input.get(OPT_MAIL_PASSWORD) or (options.get(OPT_MAIL_PASSWORD, "") if same else "")
        if not password:
            return "mail_password"
        if not (same and password == options.get(OPT_MAIL_PASSWORD)):
            try:
                await self.hass.async_add_executor_job(parcel_mail.check_login, server, user, password)
            except parcel_mail.MailError as e:
                return f"mail_{e}"
        options.update({OPT_MAIL_SERVER: server, OPT_MAIL_USER: user, OPT_MAIL_PASSWORD: password})
        return ""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = dict(self.config_entry.options)
        errors: dict[str, str] = {}
        if user_input is not None:
            for key in ENTITY_OPTIONS:               # a field left empty removes the setting; quiet hours stay untouched
                if user_input.get(key):
                    options[key] = user_input[key]
                else:
                    options.pop(key, None)
            options[OPT_ARCHIVE] = bool(user_input.get(OPT_ARCHIVE, options.get(OPT_ARCHIVE, False)))
            if not (error := await self._mail(user_input, options)):
                return self.async_create_entry(data=options)
            errors["base"] = error
            options.update({k: v for k, v in user_input.items() if k in (OPT_MAIL_SERVER, OPT_MAIL_USER)})

        notify = sorted(f"notify.{s}" for s in self.hass.services.async_services_for_domain("notify") if s != "send_message")
        schema = vol.Schema({
            vol.Optional(OPT_DOORBELL, description={"suggested_value": options.get(OPT_DOORBELL)}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["event", "binary_sensor"])),
            vol.Optional(OPT_RESIDENTS, description={"suggested_value": options.get(OPT_RESIDENTS)}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="person", multiple=True)),
            vol.Optional(OPT_NOTIFY, description={"suggested_value": options.get(OPT_NOTIFY)}): selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify, multiple=True, custom_value=True,
                                              mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional(OPT_FRONT_DOOR, description={"suggested_value": options.get(OPT_FRONT_DOOR)}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])),
            vol.Optional(OPT_TTS, description={"suggested_value": options.get(OPT_TTS)}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="tts")),
            vol.Optional(OPT_PARCEL, description={"suggested_value": options.get(OPT_PARCEL)}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])),
            vol.Optional(OPT_MAIL_USER, description={"suggested_value": options.get(OPT_MAIL_USER)}): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)),
            vol.Optional(OPT_MAIL_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            vol.Optional(OPT_MAIL_SERVER, description={"suggested_value": options.get(OPT_MAIL_SERVER, parcel_mail.DEFAULT_SERVER)}):
                selector.TextSelector(),
            vol.Optional(OPT_ARCHIVE, default=bool(options.get(OPT_ARCHIVE, False))): selector.BooleanSelector(),
        })
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

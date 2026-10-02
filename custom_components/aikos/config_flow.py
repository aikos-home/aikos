"""Setting up aikos (one click) and its options: doorbell, residents and their phones for the ring push; the call archive.

Daily settings such as quiet hours are entities of the "aikos" device, not options.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DOMAIN, OPT_ARCHIVE, OPT_DOORBELL, OPT_NOTIFY, OPT_RESIDENTS

RING_OPTIONS = (OPT_DOORBELL, OPT_RESIDENTS, OPT_NOTIFY)


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
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = dict(self.config_entry.options)
        if user_input is not None:
            for key in RING_OPTIONS:                 # a field left empty removes the setting; quiet hours stay untouched
                if user_input.get(key):
                    options[key] = user_input[key]
                else:
                    options.pop(key, None)
            options[OPT_ARCHIVE] = bool(user_input.get(OPT_ARCHIVE, False))
            return self.async_create_entry(data=options)

        notify = sorted(f"notify.{s}" for s in self.hass.services.async_services_for_domain("notify") if s != "send_message")
        schema = vol.Schema({
            vol.Optional(OPT_DOORBELL, description={"suggested_value": options.get(OPT_DOORBELL)}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["event", "binary_sensor"])),
            vol.Optional(OPT_RESIDENTS, description={"suggested_value": options.get(OPT_RESIDENTS)}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="person", multiple=True)),
            vol.Optional(OPT_NOTIFY, description={"suggested_value": options.get(OPT_NOTIFY)}): selector.SelectSelector(
                selector.SelectSelectorConfig(options=notify, multiple=True, custom_value=True,
                                              mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional(OPT_ARCHIVE, default=bool(options.get(OPT_ARCHIVE, False))): selector.BooleanSelector(),
        })
        return self.async_show_form(step_id="init", data_schema=schema)

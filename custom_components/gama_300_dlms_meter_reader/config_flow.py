from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant

from .const import DOMAIN  # pylint:disable=unused-import
from .hub import Hub

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({
    ("host"): str,
    ("port"): int,
    ("serial"): int,
    vol.Required(
        "entity_type",
        default="Default",
    ): vol.In(["Default", "IP", "Serial"]),
})

async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate that the user input allows us to connect to the meter."""
    if len(data["host"]) < 3:
        raise InvalidHost

    probe_hub = Hub(hass, data["host"], data["port"], data["serial"], data["entity_type"])
    try:
        connected = await hass.async_add_executor_job(probe_hub.test_connection)
    except Exception as err:
        raise CannotConnect from err
    finally:
        await hass.async_add_executor_job(probe_hub.disconnect)

    if not connected:
        raise CannotConnect

    return {"title": data["host"]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidHost:
                errors["host"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(
                    f"{user_input['host']}:{user_input['port']}:{user_input['serial']}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""

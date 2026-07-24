from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from . import hub
from .const import DOMAIN

PLATFORMS: list[str] = ["sensor"]

_LOGGER = logging.getLogger(__name__)


async def _cleanup_failed_setup(hass: HomeAssistant, entry: ConfigEntry, meter_hub: hub.Hub) -> None:
    """Remove the hub from hass.data and close its session."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    try:
        await hass.async_add_executor_job(meter_hub.disconnect)
    except Exception:
        _LOGGER.debug("Disconnect after failed platform setup also failed", exc_info=True)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Connect the meter session, then set up platforms."""
    entity_type = entry.data.get("entity_type") or ""

    meter_hub = hub.Hub(hass, entry.data["host"], entry.data["port"], entry.data["serial"], entity_type)

    try:
        await hass.async_add_executor_job(meter_hub.connect)
    except Exception as err:
        raise ConfigEntryNotReady(f"Could not connect to meter at {entry.data['host']}") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = meter_hub

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await _cleanup_failed_setup(hass, entry, meter_hub)
        raise
    except asyncio.CancelledError:
        await _cleanup_failed_setup(hass, entry, meter_hub)
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms, then close the meter session."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        meter_hub = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if meter_hub is not None:
            await hass.async_add_executor_job(meter_hub.disconnect)

    return unload_ok

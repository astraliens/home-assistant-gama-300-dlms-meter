from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .capabilities import discover_capabilities
from .const import (
    CONF_CAPABILITIES,
    CONF_DISPLAY_HOST,
    DEFAULT_DIAG_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_DIAG_SCAN_INTERVAL,
    MAX_SCAN_INTERVAL,
    MIN_DIAG_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    OPT_DIAG_SCAN_INTERVAL,
    OPT_SCAN_INTERVAL,
    THRESHOLD_DEFAULTS,
    build_meter_unique_id,
)
from .hub import Hub, ReconfigureWrongMeterError

_LOGGER = logging.getLogger(__name__)

# Bounds how long the reconfigure flow waits for the probe; the underlying
# blocking connect attempt is not itself cancellable, see hub.reconfigure_probe.
_PROBE_TIMEOUT = 15

# States where HA itself is in the middle of a setup/unload transition for
# this entry. Nothing about them tells us whether a connection attempt is
# in flight, and there is no safe moment to start our own -- ask the user to
# retry once the entry settles into a steady state instead of guessing.
_TRANSITIONAL_STATES = {
    ConfigEntryState.SETUP_IN_PROGRESS,
    ConfigEntryState.UNLOAD_IN_PROGRESS,
    ConfigEntryState.MIGRATION_ERROR,
    ConfigEntryState.FAILED_UNLOAD,
}


def _connection_fields(defaults: dict[str, Any] | None = None) -> dict:
    """Host/port fields shared by the user and reconfigure steps.

    Split out so a future transport-choice step (TCP vs serial) can add a
    different field set here without rewriting the surrounding step.
    """
    defaults = defaults or {}
    host_key = (
        vol.Required("host", default=defaults["host"])
        if "host" in defaults
        else vol.Required("host")
    )
    port_key = (
        vol.Required("port", default=defaults["port"])
        if "port" in defaults
        else vol.Required("port")
    )
    return {host_key: str, port_key: int}


DATA_SCHEMA = vol.Schema({
    **_connection_fields(),
    vol.Required("serial"): int,
    vol.Required(
        "entity_type",
        default="Default",
    ): vol.In(["Default", "IP", "Serial"]),
})


def _duplicate_meter_serial_exists(hass: HomeAssistant, serial, *, skip_entry_id: str | None = None) -> bool:
    """True if some entry -- migrated or legacy -- already targets this meter.

    Checked against entry.data directly (not unique_id) so a not-yet-migrated
    legacy entry cannot be double-added before the config-entry migration runs.
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == skip_entry_id:
            continue
        if entry.data.get("serial") == serial:
            return True
    return False


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

    return {
        "title": data["host"],
        "capabilities": getattr(probe_hub, "last_probe_capabilities", None),
    }


async def _probe_reconfigure_candidate(
    hass: HomeAssistant, meter_hub: Hub, host: str, port: int, expected_serial
) -> Any:
    """Run the reversible Hub-level probe with a bound on how long the flow waits.

    A timeout here only stops the flow from waiting; hub.reconfigure_probe
    always restores the running session on its own executor thread before it
    returns, whatever the outcome, so an abandoned wait never leaves the
    entry without a session. Returns the candidate's capability snapshot (or
    None) derived from that same probe connection.
    """
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT):
            await hass.async_add_executor_job(
                meter_hub.reconfigure_probe, host, port, expected_serial
            )
    except ReconfigureWrongMeterError as err:
        raise WrongMeter from err
    except Exception as err:  # pylint: disable=broad-except
        raise CannotConnect from err
    return getattr(meter_hub, "last_probe_capabilities", None)


async def _probe_reconfigure_candidate_unloaded(
    hass: HomeAssistant, host: str, port: int, serial, entity_type: str
) -> Any:
    """Validate a candidate when nothing is running or scheduled for this entry.

    Used for a plain not_loaded/setup_error entry, and for setup_retry after
    the caller has already stopped the pending retry (see async_step_reconfigure).
    Either way there is no live session to protect and no lock dance is
    needed: connect a temporary hub, read what we can, then always disconnect it.
    Returns the candidate's capability snapshot (or None).
    """
    probe_hub = Hub(hass, host, port, serial, entity_type)
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT):
            serial_value = await hass.async_add_executor_job(
                probe_hub.read_serial_after_connect
            )
    except Exception as err:  # pylint: disable=broad-except
        raise CannotConnect from err
    finally:
        await hass.async_add_executor_job(probe_hub.disconnect)

    if serial_value is not None and str(serial_value) != str(serial):
        raise WrongMeter

    return getattr(probe_hub, "last_probe_capabilities", None)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    VERSION = 1
    MINOR_VERSION = 3
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            # Checked before validate_input opens any connection: probing here
            # first would open a second TCP connection to a gateway an existing
            # entry already holds a session on, before we even know this is a
            # duplicate.
            if _duplicate_meter_serial_exists(self.hass, user_input["serial"]):
                return self.async_abort(reason="already_configured")

            await self.async_set_unique_id(build_meter_unique_id(user_input["serial"]))
            self._abort_if_unique_id_configured()

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
                entry_data = {
                    **user_input,
                    CONF_CAPABILITIES: info.get("capabilities") or discover_capabilities(()),
                }
                # No dedicated threshold step: seed every default now so the
                # device's Configuration numbers show real values immediately.
                entry_options = {**THRESHOLD_DEFAULTS}
                return self.async_create_entry(
                    title=info["title"], data=entry_data, options=entry_options
                )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(self, user_input=None):
        """Point an existing entry at a new host/port. Serial and entity_type are fixed."""
        reconfigure_entry = self._get_reconfigure_entry()
        serial = reconfigure_entry.data.get("serial")

        # A legacy or migration-collided entry never reaches the meter:{serial}
        # key by itself; catch that here instead of silently reconfiguring
        # something whose identity is not what it should be.
        await self.async_set_unique_id(build_meter_unique_id(serial))
        self._abort_if_unique_id_mismatch(reason="duplicate_meter_identity")

        old_host = reconfigure_entry.data["host"]
        old_port = reconfigure_entry.data["port"]
        errors: dict[str, str] = {}

        if user_input is not None:
            new_host = user_input["host"]
            new_port = user_input["port"]

            if new_host == old_host and new_port == old_port:
                return self._finish_reconfigure(
                    reconfigure_entry, new_host, new_port, reload_now=False
                )

            state = reconfigure_entry.state
            entity_type = reconfigure_entry.data.get("entity_type") or ""

            if state in _TRANSITIONAL_STATES:
                # HA is itself mid setup/unload right now; a connection
                # attempt could already be in flight for this entry and there
                # is no safe way to tell. Wait it out instead of racing it.
                errors["base"] = "entry_busy"
            elif state is ConfigEntryState.LOADED:
                meter_hub = self.hass.data.get(DOMAIN, {}).get(reconfigure_entry.entry_id)
                try:
                    if meter_hub is None:
                        # Should not happen while LOADED; treat defensively
                        # as any other probe failure rather than crashing.
                        raise CannotConnect
                    candidate_capabilities = await _probe_reconfigure_candidate(
                        self.hass, meter_hub, new_host, new_port, serial
                    )
                except WrongMeter:
                    return self.async_abort(reason="wrong_meter")
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                else:
                    # The central update listener is the only reload path
                    # here; calling the reloading helper too would reload
                    # twice.
                    return self._finish_reconfigure(
                        reconfigure_entry, new_host, new_port,
                        reload_now=False, capabilities=candidate_capabilities,
                    )
            elif state is ConfigEntryState.SETUP_RETRY:
                # HA is actively retrying async_setup_entry against the OLD
                # endpoint in the background. Stop that first so our probe
                # of the NEW endpoint cannot run concurrently with it -- both
                # could be the same single-client gateway under a different
                # name. This only cancels the pending retry timer; nothing
                # was ever connected to release.
                try:
                    unloaded = await self.hass.config_entries.async_unload(
                        reconfigure_entry.entry_id
                    )
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.warning(
                        "Could not stop the pending setup_retry before a "
                        "reconfigure probe",
                        exc_info=True,
                    )
                    unloaded = False

                if not unloaded:
                    # A state race (or a refusal we did not expect) -- do not
                    # probe against a session we cannot be sure is not still
                    # running. async_unload already left the entry exactly
                    # where its own outcome dictates; we have not touched
                    # anything ourselves yet.
                    errors["base"] = "entry_busy"
                else:
                    # From here on, every non-success exit -- a caught probe
                    # failure, an unexpected exception, or the flow itself
                    # being cancelled/abandoned -- must best-effort put the
                    # entry back to retrying the old (unchanged) data instead
                    # of leaving it stuck not_loaded with nothing scheduled.
                    must_resume = True
                    try:
                        try:
                            candidate_capabilities = await _probe_reconfigure_candidate_unloaded(
                                self.hass, new_host, new_port, serial, entity_type
                            )
                        except WrongMeter:
                            return self.async_abort(reason="wrong_meter")
                        except CannotConnect:
                            errors["base"] = "cannot_connect"
                        else:
                            must_resume = False
                            return self._finish_reconfigure(
                                reconfigure_entry, new_host, new_port,
                                reload_now=True, capabilities=candidate_capabilities,
                            )
                    finally:
                        if must_resume:
                            try:
                                self.hass.config_entries.async_schedule_reload(
                                    reconfigure_entry.entry_id
                                )
                            except Exception:  # pylint: disable=broad-except
                                _LOGGER.warning(
                                    "Could not reschedule setup after an "
                                    "interrupted reconfigure probe for a "
                                    "not_loaded entry",
                                    exc_info=True,
                                )
            else:
                # NOT_LOADED (including user-disabled) or SETUP_ERROR: no
                # connection is running or scheduled for this entry, so a
                # plain probe cannot race anything.
                try:
                    candidate_capabilities = await _probe_reconfigure_candidate_unloaded(
                        self.hass, new_host, new_port, serial, entity_type
                    )
                except WrongMeter:
                    return self.async_abort(reason="wrong_meter")
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                else:
                    # Nothing set up a listener for this entry yet; trigger
                    # setup ourselves, unless the user disabled it on purpose.
                    reload_now = reconfigure_entry.disabled_by is None
                    return self._finish_reconfigure(
                        reconfigure_entry, new_host, new_port,
                        reload_now=reload_now, capabilities=candidate_capabilities,
                    )

        schema = vol.Schema(_connection_fields({"host": old_host, "port": old_port}))
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
            description_placeholders={"serial": str(serial)},
        )

    def _finish_reconfigure(
        self, entry, new_host: str, new_port: int, *, reload_now: bool, capabilities=None
    ):
        """Persist the new endpoint.

        Normally the central listener is the only reload path (reload_now is
        False): calling the reloading helper as well would double-reload.
        reload_now is only True when nothing set that listener up yet (the
        entry was not loaded), so this is the one place that must trigger
        setup itself, and doing so here cannot race a second reload.

        capabilities, when not None, replaces the stored capability snapshot
        with the one just derived from the successful probe -- internal
        entry.data otherwise stays untouched (data_updates merges, it never
        replaces the whole dict).
        """
        data_updates: dict[str, Any] = {"host": new_host, "port": new_port}
        if new_host != entry.data.get("host") and CONF_DISPLAY_HOST not in entry.data:
            data_updates[CONF_DISPLAY_HOST] = entry.data.get("host")
        if capabilities is not None:
            data_updates[CONF_CAPABILITIES] = capabilities
        if reload_now:
            return self.async_update_reload_and_abort(entry, data_updates=data_updates)
        return self.async_update_and_abort(entry, data_updates=data_updates)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "OptionsFlowHandler":
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow: poll intervals only. Connection fields live in reconfigure."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        current = self.config_entry.options
        if user_input is not None:
            new_options = dict(current)
            new_options[OPT_SCAN_INTERVAL] = user_input[OPT_SCAN_INTERVAL]
            new_options[OPT_DIAG_SCAN_INTERVAL] = user_input[OPT_DIAG_SCAN_INTERVAL]
            return self.async_create_entry(title="", data=new_options)

        schema = vol.Schema({
            vol.Required(
                OPT_SCAN_INTERVAL,
                default=current.get(OPT_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
            vol.Required(
                OPT_DIAG_SCAN_INTERVAL,
                default=current.get(OPT_DIAG_SCAN_INTERVAL, DEFAULT_DIAG_SCAN_INTERVAL),
            ): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_DIAG_SCAN_INTERVAL, max=MAX_DIAG_SCAN_INTERVAL)
            ),
        })
        return self.async_show_form(step_id="init", data_schema=schema)


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""


class WrongMeter(exceptions.HomeAssistantError):
    """Error to indicate the candidate endpoint answers as a different meter."""

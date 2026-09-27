"""Hub that owns the DLMS meter session for a config entry."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .capabilities import discover_capabilities as _discover_capabilities
from .device_info import build_device_info as _build_device_info
from .dlms_read_data.MeterClient import MeterClient
from .const import build_device_identifier

_LOGGER = logging.getLogger(__name__)


class ReconfigureWrongMeterError(Exception):
    """Raised by reconfigure_probe() when the candidate is a different meter."""

    def __init__(self, serial) -> None:
        super().__init__(f"candidate reports serial {serial!r}")
        self.serial = serial


class Hub:
    """Owns one MeterClient session per config entry.

    Construction does no network I/O. connect/disconnect/read are blocking —
    call them through the executor from async code.
    """

    # OBIS -> raw config metadata key consumed by device_info.build_device_info().
    # Keyed by OBIS because the field name is an implementation detail, not
    # a 1:1 DeviceInfo mapping (e.g. model_id_raw feeds both model_id and model).
    _DEVICE_INFO_OBIS = {
        "1.0.96.1.1.255": "model_id_raw",
        "1.0.96.1.2.255": "hw_config_raw",
        "1.0.0.0.0.255": "serial_number_raw",
        "1.0.0.2.0.255": "sw_version_raw",
    }

    # Same OBIS as _DEVICE_INFO_OBIS["serial_number"]; attribute index from meter_param.json.
    _SERIAL_OBIS = "1.0.0.0.0.255"
    _SERIAL_OBIS_ATTR = 2

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        serial: int,
        entity_type: str,
        display_host: str | None = None,
    ) -> None:
        """Init hub.

        display_host overrides host for the device name and the "IP" entity
        suffix only; it never affects the connection or the meter identity.
        Reconfigure freezes it the first time the real host changes.
        """
        self._host = host
        self._port = port
        self._serial = serial
        self._hass = hass
        self.meter_client = MeterClient(host, port, serial)
        self._display_host = display_host or host
        self._name = "DLMS Meter " + self._display_host
        self._entity_type = entity_type.lower()

        # Identity (unique_id, device identifiers) is always the serial, independent
        # of entity_type, so it survives host/port changes. display_suffix is the
        # separate, purely cosmetic name suffix users already rely on.
        self.identity_key = str(serial)
        self.display_suffix: str | None = None

        if self._entity_type == "ip":
            self.display_suffix = self._display_host.lower()
        elif self._entity_type == "serial":
            self.display_suffix = str(serial)
            self._name = "DLMS Meter " + self._display_host + " (" + str(serial) + ")"

        self.meters = [
            DLMSMeter(f"{self.identity_key}_1", f"{self._name}", self),
        ]

        # Raw config OBIS values, keyed by the names build_device_info() expects.
        # Populated by the config coordinator; consumed by build_device_info().
        self._config_metadata: dict[str, str] = {}

        # Capability snapshot from the most recent probe/connect performed by
        # this Hub instance (test_connection, reconfigure_probe, or
        # read_serial_after_connect); None until one of them has run. Not
        # touched by the normal read_all_data()/read_all_config() poll path.
        self.last_probe_capabilities: dict | None = None

    def discover_capabilities(self) -> dict:
        """Capability snapshot derived from this session's association view.

        Pure aside from list_available_obis(), which itself does no I/O (the
        view was already fetched by connect()). Never raises: an unreadable
        view just yields empty capability lists instead of failing setup.
        """
        try:
            available = self.meter_client.list_available_obis()
        except Exception:  # pylint: disable=broad-except
            available = set()
        return _discover_capabilities(available)

    def update_device_info(self, config_items) -> None:
        """Refresh cached config metadata from a config read; skip empty so partial reads keep prior values."""
        for item in config_items:
            field = self._DEVICE_INFO_OBIS.get(item.get("meter_param"))
            if field is None:
                continue
            value = item.get("value")
            if value is not None and value != "":
                self._config_metadata[field] = value

    def build_device_info(self) -> dict:
        """Shared DeviceInfo for every entity/platform on this device.

        Pure aside from reading already-cached state: no DLMS I/O here.
        """
        return _build_device_info(
            identifiers={build_device_identifier(self.identity_key)},
            name=self._name,
            flag_id=self.meter_client.get_manufacturer_flag_id(),
            **self._config_metadata,
        )

    @property
    def endpoint_label(self) -> str:
        """Current connection endpoint for the diagnostic Connection sensor.

        TCP host:port for now; a future serial transport supplies its own
        device path here instead, without the sensor knowing the difference.
        """
        return f"{self._host}:{self._port}"

    @property
    def manufacturer_name(self) -> str | None:
        """Resolved manufacturer DeviceInfo already carries, or None if omitted.

        No extra DLMS read: this is the same value build_device_info() publishes.
        """
        return self.build_device_info().get("manufacturer")

    @property
    def model_name(self) -> str | None:
        """Resolved model DeviceInfo already carries, or None if omitted.

        No extra DLMS read. This is the catalog name (for example GAMA 300),
        not the raw model id register.
        """
        return self.build_device_info().get("model")

    @property
    def hub_id(self) -> str:
        """ID for hub."""
        return self.identity_key

    @property
    def online(self) -> bool:
        """Cached session flag; no network I/O."""
        return self.meter_client.is_connected()

    @property
    def closed(self) -> bool:
        """Whether close() has permanently retired this hub's session."""
        return self.meter_client._closed

    def connect(self) -> None:
        self.meter_client.connect()

    def disconnect(self) -> None:
        self.meter_client.disconnect()

    def close(self) -> None:
        """Permanently retire this hub's session; see MeterClient.close()."""
        self.meter_client.close()

    def reconnect(self) -> None:
        self.meter_client.reconnect()

    def test_connection(self) -> bool:
        """Connect and return whether the association is up. Raises on failure."""
        self.meter_client.connect()
        self.last_probe_capabilities = self.discover_capabilities()
        return self.meter_client.is_connected()

    def read_all_data(self):
        return self.meter_client.read_all_data()

    def read_all_config(self):
        return self.meter_client.read_all_config()

    def reconfigure_probe(
        self, host: str, port: int, expected_serial: int | None = None
    ) -> object:
        """Validate a candidate host/port for reconfigure without a second live connection.

        A coordinator poll landing mid-probe would otherwise reconnect this hub's
        own session the moment it is closed (read_item() auto-reconnects), which
        could open a second TCP connection to a gateway that only accepts one
        client. Holding the session lock for the whole probe blocks that: any
        concurrent read/reconnect call waits for the same lock and only proceeds
        once this method has restored (or given up on) the old session.

        The old session is always reconnected before this returns or raises,
        on every outcome -- not just on failure. This is deliberate: the flow
        awaiting this call may give up on a timeout while this (blocking,
        uncancellable) call keeps running on its executor thread, so whether
        the flow is still there to act on a successful outcome cannot be
        relied on. A probe is read-only validation only; it never switches
        this hub onto the candidate itself -- an actual switch only happens
        once the caller persists the new host/port and the entry reloads.
        Making every outcome self-restoring keeps the running session correct
        regardless of what the caller does with the result afterwards.

        If expected_serial is given and the candidate's own serial OBIS can be
        read, a mismatch raises ReconfigureWrongMeterError instead of
        returning, after the old session has already been restored.

        Returns the serial OBIS value read from the candidate, or None if the
        association came up but that attribute could not be read.
        """
        client = self.meter_client
        with client._lock:
            was_connected = client.is_connected()
            client.disconnect()

            probe_client = MeterClient(host, port, self._serial)
            connect_error: Exception | None = None
            serial_value: object = None
            try:
                probe_client.connect()
            except Exception as err:  # pylint: disable=broad-except
                connect_error = err
            else:
                try:
                    candidate_capabilities = _discover_capabilities(
                        probe_client.list_available_obis()
                    )
                except Exception:  # pylint: disable=broad-except
                    candidate_capabilities = None
                if candidate_capabilities is not None:
                    self.last_probe_capabilities = candidate_capabilities
                try:
                    serial_value = probe_client.read_item(
                        self._SERIAL_OBIS, self._SERIAL_OBIS_ATTR
                    )
                except Exception:  # pylint: disable=broad-except
                    serial_value = None
            finally:
                probe_client.disconnect()

            if was_connected:
                try:
                    client.connect()
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.warning(
                        "Could not restore the meter session after a "
                        "reconfigure probe; the next poll will reconnect it",
                        exc_info=True,
                    )

        if connect_error is not None:
            raise connect_error

        if (
            expected_serial is not None
            and serial_value is not None
            and str(serial_value) != str(expected_serial)
        ):
            raise ReconfigureWrongMeterError(serial_value)

        return serial_value

    def read_serial_after_connect(self) -> object:
        """Connect (if needed) and return the serial OBIS value, or None if unreadable.

        For a fresh probe hub with no concurrent session to protect (the
        entry is not currently loaded, e.g. it is in setup_retry). Callers
        must still call disconnect() themselves; unlike reconfigure_probe()
        there is no running session here for this method to manage.
        """
        self.meter_client.connect()
        self.last_probe_capabilities = self.discover_capabilities()
        try:
            return self.meter_client.read_item(self._SERIAL_OBIS, self._SERIAL_OBIS_ATTR)
        except Exception:  # pylint: disable=broad-except
            return None


class DLMSMeter:
    """A single meter exposed by the hub (device for HA)."""

    def __init__(self, dlmsmeterid: str, name: str, hub: Hub) -> None:
        """Init dlmsmeter. Does not open a connection."""
        self._id = dlmsmeterid
        self.hub = hub
        self.name = name
        # Populated later when a connected session can read them.
        self.model = None
        self.firmware_version = None

    @property
    def dlmsmeter_id(self) -> str:
        """Return ID for dlmsmeter."""
        return self._id

    def get_available_params(self):
        meter_client = self.hub.meter_client
        return meter_client.filter_known(meter_client.GetDataList())

    def get_available_diag_params(self):
        meter_client = self.hub.meter_client
        return meter_client.filter_known(meter_client.GetMeterConfigList())

    @property
    def online(self) -> bool:
        """Cached session flag; no network I/O."""
        return self.hub.meter_client.is_connected()

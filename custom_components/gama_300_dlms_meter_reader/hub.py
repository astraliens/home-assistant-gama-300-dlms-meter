"""Hub that owns the DLMS meter session for a config entry."""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from .dlms_read_data.MeterClient import MeterClient


class Hub:
    """Owns one MeterClient session per config entry.

    Construction does no network I/O. connect/disconnect/read are blocking —
    call them through the executor from async code.
    """

    def __init__(self, hass: HomeAssistant, host: str, port: int, serial: int, entity_type: str) -> None:
        """Init hub."""
        self._host = host
        self._port = port
        self._serial = serial
        self._hass = hass
        self.meter_client = MeterClient(host, port, serial)
        self._name = "DLMS Meter " + host
        self._entity_type = entity_type.lower()
        self._id = host.lower()

        if self._entity_type == "serial":
            self._id = str(serial)
            self._name = "DLMS Meter " + host + " (" + str(serial) + ")"

        self.meters = [
            DLMSMeter(f"{self._id}_1", f"{self._name}", self),
        ]

    @property
    def hub_id(self) -> str:
        """ID for hub."""
        return self._id

    @property
    def online(self) -> bool:
        """Cached session flag; no network I/O."""
        return self.meter_client.is_connected()

    def connect(self) -> None:
        self.meter_client.connect()

    def disconnect(self) -> None:
        self.meter_client.disconnect()

    def reconnect(self) -> None:
        self.meter_client.reconnect()

    def test_connection(self) -> bool:
        """Connect and return whether the association is up. Raises on failure."""
        self.meter_client.connect()
        return self.meter_client.is_connected()

    def read_all_data(self):
        return self.meter_client.read_all_data()

    def read_all_config(self):
        return self.meter_client.read_all_config()


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
        return self.hub.meter_client.GetDataList()

    def get_available_diag_params(self):
        return self.hub.meter_client.GetMeterConfigList()

    @property
    def online(self) -> bool:
        """Cached session flag; no network I/O."""
        return self.hub.meter_client.is_connected()

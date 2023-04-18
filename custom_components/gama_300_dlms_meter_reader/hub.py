"""A demonstration 'hub' that connects several devices."""
from __future__ import annotations
from .dlms_read_data.MeterClient import MeterClient

# In a real implementation, this would be in an external library that's on PyPI.
# The PyPI package needs to be included in the `requirements` section of manifest.json
# See https://developers.home-assistant.io/docs/creating_integration_manifest
# for more information.
# This hub always returns 3 meters.
import asyncio
import random

from homeassistant.core import HomeAssistant
import time
import logging
_LOGGER = logging.getLogger(__name__)

class Hub:
    manufacturer = "DLMS Meter"

    def __init__(self, hass: HomeAssistant, host: str, port: int, serial: int) -> None:
        """Init hub."""
        self._host = host
        self._port = port
        self._serial = serial
        self._hass = hass
        self.meter_client=MeterClient(host,port,serial)
        self._name = "DLMS Meter " + host
        self._id = host.lower()
        #self.manufacturer=self.meter_client.get_model2()
        self.manufacturer='DLMS Meter Manufacturer'
        self.meters = [
            DLMSMeter(f"{self._id}_1", f"{self._name}", self),
            #DLMSMeter(f"{self._id}_2", f"{self._name} 2", self),
            #DLMSMeter(f"{self._id}_3", f"{self._name} 3", self),
        ]
        self.online = True

    @property
    def hub_id(self) -> str:
        """ID for hub."""
        return self._id

    async def test_connection(self) -> bool:
        """Test connectivity with dlmsmeter"""
        #await asyncio.sleep(1)
        return self.meter_client.online()


class DLMSMeter:
    """dlmsmeter (device for HA)."""

    def __init__(self, dlmsmeterid: str, name: str, hub: Hub) -> None:
        """Init dlmsmeter."""
        self._id = dlmsmeterid
        self.hub = hub
        self.name = name
        self._callbacks = set()
        self._loop = asyncio.get_event_loop()
        self.hub.meter_client.connect()
        self.model=self.hub.meter_client.get_model()
        self.firmware_version=self.hub.meter_client.get_firmware_version()        
        
    @property
    def dlmsmeter_id(self) -> str:
        """Return ID for dlmsmeter."""
        return self._id

    @property
    def position(self):
        """Return position for dlmsmeter."""
        return self._current_position

    async def set_position(self, position: int) -> None:
        """
        Set cover to the given position.

        State is announced a random number of seconds later.
        """
        self._target_position = position

        # Update the moving status, and broadcast the update
        self.moving = position - 50
        await self.publish_updates()

        self._loop.create_task(self.delayed_update())

    async def delayed_update(self) -> None:
        """Publish updates, with a random delay to emulate interaction with device."""
        await asyncio.sleep(20)
        self.moving = 0
        await self.publish_updates()

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register callback, called when DLMSMeter changes state."""
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove previously registered callback."""
        self._callbacks.discard(callback)

    # In a real implementation, this library would call it's call backs when it was
    # notified of any state changeds for the relevant device.
    async def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
        self._current_position = self._target_position
        for callback in self._callbacks:
            callback()

    def update_data(self):
        return self.hub.meter_client.ReadAllConfig()

    def get_available_params(self):
        return self.hub.meter_client.GetDataList()
    
    def get_available_diag_params(self):
        return self.hub.meter_client.GetMeterConfigList()    

    @property
    def online(self) -> float:
        """DLMSMeter is online."""
        #  Returns True if online,
        # False if offline.
        self.update_data()
        return self.hub.meter_client.online()

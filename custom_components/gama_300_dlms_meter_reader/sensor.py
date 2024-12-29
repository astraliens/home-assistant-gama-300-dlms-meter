"""Platform for sensor integration."""
# This file shows the setup for the sensors associated with the cover.
# They are setup in the same way with the call to the async_setup_entry function
# via HA from the module __init__. Each sensor has a device_class, this tells HA how
# to display it in the UI (for know types). The unit_of_measurement property tells HA
# what the unit is, so it can display the correct range. For predefined types (such as
# battery), the unit_of_measurement should match what's expected.
import random

from homeassistant.const import (
    ATTR_VOLTAGE,
    PERCENTAGE,
    EntityCategory
)
from homeassistant.helpers.entity import Entity

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
    SensorEntity
)

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
import async_timeout
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.components.light import LightEntity





from .const import DOMAIN
from datetime import timedelta
import time

import logging
_LOGGER = logging.getLogger(__name__)
#SCAN_INTERVAL = timedelta(seconds=5)


# See cover.py for more details.
# Note how both entities for each dlmsmeter sensor (battry and illuminance) are added at
# the same time to the same list. This way only a single async_add_devices call is
# required.
async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    hub = hass.data[DOMAIN][config_entry.entry_id]

    coordinator = DLMSMeterDataCoordinator(hass, hub)
    await coordinator.async_config_entry_first_refresh()

    coordinator_diag = DLMSMeterConfigCoordinator(hass, hub)
    await coordinator_diag.async_config_entry_first_refresh()    


    new_devices = []
    for dlmsmeter in hub.meters:
        available_params=dlmsmeter.get_available_params()
        for dlmsmeter_param in available_params:
            match dlmsmeter_param["sensor"]:
                case "voltage":
                    new_devices.append(SensorDLMSMeterVoltage(coordinator, dlmsmeter_param))
                case "current":
                    new_devices.append(SensorDLMSMeterCurrent(coordinator, dlmsmeter_param))
                case "frequency":
                    new_devices.append(SensorDLMSMeterFrequency(coordinator, dlmsmeter_param))
                case "power":
                    new_devices.append(SensorDLMSMeterPower(coordinator, dlmsmeter_param))
                case "power_factor":
                    new_devices.append(SensorDLMSMeterPowerFactor(coordinator, dlmsmeter_param))
                case "energy_total":
                    new_devices.append(SensorDLMSMeterEnergyTotal(coordinator, dlmsmeter_param))
                case "energy_total_increasing":
                    new_devices.append(SensorDLMSMeterEnergyTotalIncreasing(coordinator, dlmsmeter_param))
                case "counter":
                    new_devices.append(SensorDLMSMeterCounter(coordinator, dlmsmeter_param))
                case "info":
                    new_devices.append(SensorDLMSMeterInfo(coordinator, dlmsmeter_param))
                case "time_duration":
                    new_devices.append(SensorDLMSMeterTimeDuration(coordinator, dlmsmeter_param))

        available_diag_params=dlmsmeter.get_available_diag_params()
        for dlmsmeter_param in available_diag_params:
            match dlmsmeter_param["sensor"]:
                case "info":
                    new_devices.append(SensorDLMSMeterDiagInfo(coordinator_diag, dlmsmeter_param))

    if new_devices:
        async_add_entities(new_devices)


class DLMSMeterDataCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    def __init__(self, hass, hub):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Meter Data Coordinator",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=3),
        )
        self.hub = hub
        self.hass=hass

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(30):
                # Grab active context variables to limit data required to be fetched from API
                # Note: using context is not required if there is no need or ability to limit
                # data retrieved from API.
                listening_idx = set(self.async_contexts())
                #return await self.hub.fetch_data(listening_idx)

                return await self.hass.async_add_executor_job(self.hub.meter_client.ReadAllDataSYNC) # nedd to avoid problem with UI freezing during data update process
                #return await self.hub.meter_client.ReadAllData()
                
        except Exception as e:
            s = str(e)
            # Raising ConfigEntryAuthFailed will cancel future updates
            # and start a config flow with SOURCE_REAUTH (async_step_reauth)
            _LOGGER.error("-------------------- COORDINATOR DATA UPDATE FAILED ----------------" + s)
            self.hub.meter_client.reconnect()
        

class DLMSMeterConfigCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    def __init__(self, hass, hub):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Meter Config Coordinator",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=600),
        )
        self.hub = hub

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(20):
                # Grab active context variables to limit data required to be fetched from API
                # Note: using context is not required if there is no need or ability to limit
                # data retrieved from API.
                listening_idx = set(self.async_contexts())
                #return await self.hub.fetch_data(listening_idx)
                return await self.hub.meter_client.ReadAllConfig()
                
        except Exception as e:
            s = str(e)
            # Raising ConfigEntryAuthFailed will cancel future updates
            # and start a config flow with SOURCE_REAUTH (async_step_reauth)
            _LOGGER.error("-------------------- COORDINATOR CONFIG UPDATE FAILED ----------------" + s)


class SensorBase(CoordinatorEntity, SensorEntity):
    """An entity using CoordinatorEntity.

    The CoordinatorEntity class provides:
      should_poll
      async_update
      async_added_to_hass
      available

    """

    device_class = ""
    state_class = "" 

    def __init__(self, coordinator, dlmsmeter_param):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self.hub=coordinator.hub
        self.dlmsmeter_param = dlmsmeter_param
        self._attr_unique_id = f"dlms_meter_{self.hub._id}_{dlmsmeter_param['meter_param']}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        test =1
        """
        #self._attr_is_on = self.coordinator.data[self.idx]["text"]
        self._attr_is_on = 1
        self.async_write_ha_state()
        """

class SensorDLMSMeter(SensorBase):
    def __init__(self, coordinator, dlmsmeter_param):
        super().__init__(coordinator, dlmsmeter_param)
        #self.sensor_name=dlmsmeter_param["text"]
        self.meter_param=dlmsmeter_param["meter_param"]
        self._attr_name = f"{dlmsmeter_param['text']}"
        
        if self.hub._entity_type == "ip":
            self._attr_name= self._attr_name + " (" + self.hub._id + ")"
        
        if self.hub._entity_type == "serial":
            self._attr_name= self._attr_name + " (" + self.hub._id + ")"
        
        #self._attr_unique_id = f"dlms_meter_{self.hub._id}_{dlmsmeter_param['meter_param']}"
        #self.sensor_name=self._attr_unique_id
        self._state = 0
        if "unit" in dlmsmeter_param :
            self._attr_native_unit_of_measurement = dlmsmeter_param["unit"]
        self.last_state=''

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        # return {"identifiers": {(DOMAIN, self.hub._id)}}

        return {
            "identifiers": {(DOMAIN, self.hub._id)},
            # If desired, the name for the device could be different to the entity
            "name": self.hub._name,
            #"sw_version": self.hub.meter_client.get_firmware_version(),
            #"model": self.hub.meter_client.get_model(),
            "manufacturer": self.hub.meter_client.get_manufacturer()
        }    

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.last_state=self.GtCurrentParamData()['value']
        self.async_write_ha_state()
        
    def GtCurrentParamData(self):
        for data_item in self.coordinator.data:
            if(data_item['meter_param']==self.meter_param):
                return data_item

    @property
    def state(self) :
        return self.last_state
        #self.coordinator.data
        #return self.GtCurrentParamData()['value']


class SensorDLMSMeterVoltage(SensorDLMSMeter):
    def __init__(self, coordinator, dlmsmeter_param):
        super().__init__(coordinator, dlmsmeter_param)
        self.state_class = SensorStateClass.MEASUREMENT
        self.device_class = SensorDeviceClass.VOLTAGE

class SensorDLMSMeterCurrent(SensorDLMSMeter):
    def __init__(self, coordinator, dlmsmeter_param):
        super().__init__(coordinator, dlmsmeter_param)
        self.state_class = SensorStateClass.MEASUREMENT
        self.device_class = SensorDeviceClass.CURRENT

class SensorDLMSMeterPowerFactor(SensorDLMSMeter):
    def __init__(self, coordinator, dlmsmeter_param):
        super().__init__(coordinator, dlmsmeter_param)
        self.state_class = SensorStateClass.MEASUREMENT
        self.device_class = SensorDeviceClass.POWER_FACTOR 

class SensorDLMSMeterFrequency(SensorDLMSMeter):
    def __init__(self, dlmsmeter, param_name):
        super().__init__(dlmsmeter, param_name)
        self.state_class = SensorStateClass.MEASUREMENT
        self.device_class = SensorDeviceClass.FREQUENCY

class SensorDLMSMeterPower(SensorDLMSMeter):
    def __init__(self, dlmsmeter, param_name):
        super().__init__(dlmsmeter, param_name)
        self.state_class = SensorStateClass.MEASUREMENT
        self.device_class = SensorDeviceClass.POWER

class SensorDLMSMeterEnergyTotal(SensorDLMSMeter):
    def __init__(self, dlmsmeter, param_name):
        super().__init__(dlmsmeter, param_name)
        self.device_class = SensorDeviceClass.ENERGY
        self.state_class = SensorStateClass.TOTAL

class SensorDLMSMeterEnergyTotalIncreasing(SensorDLMSMeter):
    def __init__(self, dlmsmeter, param_name):
        super().__init__(dlmsmeter, param_name)
        self.device_class = SensorDeviceClass.ENERGY
        self.state_class = SensorStateClass.TOTAL_INCREASING

class SensorDLMSMeterInfo(SensorDLMSMeter):
    def __init__(self, dlmsmeter, param_name):
        super().__init__(dlmsmeter, param_name)

class SensorDLMSMeterCounter(SensorDLMSMeter):
    def __init__(self, dlmsmeter, param_name):
        super().__init__(dlmsmeter, param_name)
        self.state_class = SensorStateClass.MEASUREMENT

class SensorDLMSMeterTimeDuration(SensorDLMSMeter):
    def __init__(self, dlmsmeter, param_name):
        super().__init__(dlmsmeter, param_name)
        #self.state_class = SensorStateClass.MEASUREMENT
        self.device_class = SensorDeviceClass.DURATION

class SensorDLMSMeterDiag(SensorDLMSMeter):
    entity_category = EntityCategory.DIAGNOSTIC
    def __init__(self, dlmsmeter, param_name):
        super().__init__(dlmsmeter, param_name)

class SensorDLMSMeterDiagInfo(SensorDLMSMeterDiag):
    def __init__(self, dlmsmeter, param_name):
        super().__init__(dlmsmeter, param_name)


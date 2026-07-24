"""Platform for sensor integration."""
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
import asyncio
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.components.light import LightEntity





from .const import DOMAIN
from datetime import timedelta
import time

import logging
_LOGGER = logging.getLogger(__name__)
#SCAN_INTERVAL = timedelta(seconds=5)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    hub = hass.data[DOMAIN][config_entry.entry_id]

    # One throttle for both coordinators so they do not reconnect independently.
    reconnect_throttle = _ReconnectThrottle()

    coordinator = DLMSMeterDataCoordinator(hass, hub, reconnect_throttle)
    await coordinator.async_config_entry_first_refresh()

    coordinator_diag = DLMSMeterConfigCoordinator(hass, hub, reconnect_throttle)
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


class _ReconnectThrottle:
    """Backoff for reconnect attempts during outages (5s…60s).

    Failed polls still raise UpdateFailed immediately; only reconnect is
    delayed. claim_attempt() is sync so two coordinators cannot both start
    a reconnect in the same event-loop tick.
    """

    _INITIAL_COOLDOWN = 5.0
    _MAX_COOLDOWN = 60.0

    def __init__(self):
        self._next_attempt = 0.0
        self._cooldown = self._INITIAL_COOLDOWN
        self._in_flight = False

    def claim_attempt(self):
        """Reserve a reconnect slot, or return False if still cooling down."""
        if self._in_flight or time.monotonic() < self._next_attempt:
            return False
        self._in_flight = True
        # Placeholder until release(); overwritten on normal completion.
        self._next_attempt = time.monotonic() + self._cooldown
        return True

    def release(self, success):
        """Clear in-flight and update the cooldown from the attempt result."""
        if success:
            self._cooldown = self._INITIAL_COOLDOWN
            self._next_attempt = time.monotonic()
        else:
            self._next_attempt = time.monotonic() + self._cooldown
            self._cooldown = min(self._cooldown * 2, self._MAX_COOLDOWN)
        self._in_flight = False

    def reset(self):
        """Reset after a successful poll."""
        self._cooldown = self._INITIAL_COOLDOWN
        self._next_attempt = 0.0


async def _attempt_reconnect(hass, hub, throttle):
    """Executor reconnect; only CancelledError can escape."""
    if not throttle.claim_attempt():
        return
    success = False
    try:
        await hass.async_add_executor_job(hub.reconnect)
        success = True
    except asyncio.CancelledError:
        raise
    except Exception:
        _LOGGER.debug("Reconnect attempt failed", exc_info=True)
    finally:
        throttle.release(success)


class DLMSMeterDataCoordinator(DataUpdateCoordinator):
    """Coordinator for the fast-changing measurement data."""

    def __init__(self, hass, hub, reconnect_throttle):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Meter Data Coordinator",
            update_interval=timedelta(seconds=3),
        )
        self.hub = hub
        self.hass = hass
        self._reconnect_throttle = reconnect_throttle

    async def _async_update_data(self):
        try:
            async with asyncio.timeout(30):
                data = await self.hass.async_add_executor_job(self.hub.read_all_data)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.error("Meter data update failed: %s", err)
            await _attempt_reconnect(self.hass, self.hub, self._reconnect_throttle)
            raise UpdateFailed(err) from err
        else:
            self._reconnect_throttle.reset()
            return data


class DLMSMeterConfigCoordinator(DataUpdateCoordinator):
    """Coordinator for the slow-changing diagnostic/config data."""

    def __init__(self, hass, hub, reconnect_throttle):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Meter Config Coordinator",
            update_interval=timedelta(seconds=600),
        )
        self.hub = hub
        self._reconnect_throttle = reconnect_throttle

    async def _async_update_data(self):
        try:
            async with asyncio.timeout(20):
                data = await self.hass.async_add_executor_job(self.hub.read_all_config)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.error("Meter config update failed: %s", err)
            await _attempt_reconnect(self.hass, self.hub, self._reconnect_throttle)
            raise UpdateFailed(err) from err
        else:
            self._reconnect_throttle.reset()
            return data


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
        current = self.GtCurrentParamData()
        if current is not None:
            self.last_state = current['value']
        self.async_write_ha_state()

    def GtCurrentParamData(self):
        # First refresh may leave coordinator.data as None.
        if self.coordinator.data is None:
            return None
        for data_item in self.coordinator.data:
            if(data_item['meter_param']==self.meter_param):
                return data_item
        return None

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


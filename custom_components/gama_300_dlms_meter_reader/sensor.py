"""Platform for sensor integration."""
from datetime import datetime, timedelta
import time

from homeassistant.const import EntityCategory

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
    SensorEntity
)

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
import asyncio
import homeassistant.util.dt as dt_util

from .const import DOMAIN
from .model_config import decode_model_config

import logging
_LOGGER = logging.getLogger(__name__)


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
                    # Source data labels reactive power as VA; HA POWER accepts only W.
                    if dlmsmeter_param.get("unit") == "W":
                        new_devices.append(SensorDLMSMeterPower(coordinator, dlmsmeter_param))
                    else:
                        new_devices.append(SensorDLMSMeterReactivePower(coordinator, dlmsmeter_param))
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
                case "date":
                    new_devices.append(SensorDLMSMeterDate(coordinator, dlmsmeter_param))

        available_diag_params=dlmsmeter.get_available_diag_params()
        for dlmsmeter_param in available_diag_params:
            match dlmsmeter_param["sensor"]:
                case "info":
                    if dlmsmeter_param["meter_param"] == _MODEL_CONFIG_OBIS:
                        new_devices.append(SensorDLMSMeterModelConfig(coordinator_diag, dlmsmeter_param))
                    else:
                        new_devices.append(SensorDLMSMeterDiagInfo(coordinator_diag, dlmsmeter_param))
                case "counter":
                    new_devices.append(SensorDLMSMeterDiagCounter(coordinator_diag, dlmsmeter_param))
                case "time_duration":
                    new_devices.append(SensorDLMSMeterDiagTimeDuration(coordinator_diag, dlmsmeter_param))

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
            self.hub.update_device_info(data)
            return data


class SensorBase(CoordinatorEntity, SensorEntity):
    """Base entity backed by a DataUpdateCoordinator."""

    def __init__(self, coordinator, dlmsmeter_param):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self.hub=coordinator.hub
        self.dlmsmeter_param = dlmsmeter_param
        self._attr_unique_id = f"dlms_meter_{self.hub._id}_{dlmsmeter_param['meter_param']}"


class SensorDLMSMeter(SensorBase):
    def __init__(self, coordinator, dlmsmeter_param):
        super().__init__(coordinator, dlmsmeter_param)
        self.meter_param=dlmsmeter_param["meter_param"]
        self._attr_name = f"{dlmsmeter_param['text']}"

        if self.hub._entity_type == "ip":
            self._attr_name= self._attr_name + " (" + self.hub._id + ")"

        if self.hub._entity_type == "serial":
            self._attr_name= self._attr_name + " (" + self.hub._id + ")"

        if "unit" in dlmsmeter_param :
            self._attr_native_unit_of_measurement = dlmsmeter_param["unit"]

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        info = {
            "identifiers": {(DOMAIN, self.hub._id)},
            # If desired, the name for the device could be different to the entity
            "name": self.hub._name,
            "manufacturer": self.hub.meter_client.get_manufacturer(),
        }
        # From the 600s config poll; skip fields not read yet.
        info.update(self.hub.device_info_data)
        return info

    def GtCurrentParamData(self):
        # First refresh may leave coordinator.data as None.
        if self.coordinator.data is None:
            return None
        for data_item in self.coordinator.data:
            if(data_item['meter_param']==self.meter_param):
                return data_item
        return None

    @property
    def native_value(self):
        current = self.GtCurrentParamData()
        if current is None:
            return None
        return current["value"]


class SensorDLMSMeterVoltage(SensorDLMSMeter):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.VOLTAGE

class SensorDLMSMeterCurrent(SensorDLMSMeter):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.CURRENT

class SensorDLMSMeterPowerFactor(SensorDLMSMeter):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER_FACTOR

class SensorDLMSMeterFrequency(SensorDLMSMeter):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.FREQUENCY

class SensorDLMSMeterPower(SensorDLMSMeter):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER

class SensorDLMSMeterReactivePower(SensorDLMSMeter):
    """Reactive power; source unit is mislabelled VA, so leave device_class unset."""

    _attr_state_class = SensorStateClass.MEASUREMENT

class SensorDLMSMeterEnergyTotal(SensorDLMSMeter):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL

class SensorDLMSMeterEnergyTotalIncreasing(SensorDLMSMeter):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

class SensorDLMSMeterInfo(SensorDLMSMeter):
    pass

class SensorDLMSMeterCounter(SensorDLMSMeter):
    _attr_state_class = SensorStateClass.MEASUREMENT

class SensorDLMSMeterTimeDuration(SensorDLMSMeter):
    _attr_device_class = SensorDeviceClass.DURATION

class SensorDLMSMeterDate(SensorDLMSMeter):
    """Billing-period close timestamp. GXDateTime may import under two paths; duck-type .value."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        current = self.GtCurrentParamData()
        if current is None:
            return None
        raw = getattr(current["value"], "value", None)
        if not isinstance(raw, datetime):
            return None
        # Meter reports local time when it omits the UTC deviation.
        if raw.tzinfo is None:
            raw = raw.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return dt_util.as_utc(raw)

_MODEL_OBIS = "1.0.96.1.1.255"
_MODEL_CONFIG_OBIS = "1.0.96.1.2.255"

# OBIS -> icon for diagnostic sensors. Keyed by OBIS because the display text can be reworded.
_DIAG_ICONS = {
    "1.0.96.1.1.255": "mdi:chip",
    "1.0.96.1.2.255": "mdi:cog",
    "1.0.0.0.0.255": "mdi:barcode",
    "1.0.0.0.1.255": "mdi:flag",
    "1.0.0.0.2.255": "mdi:map",
    "1.0.0.2.0.255": "mdi:update",
    "1.0.96.61.10.255": "mdi:timer-sand",
    "1.0.96.60.12.255": "mdi:flash-alert",
    "1.0.96.61.12.255": "mdi:timer-sand",
    "1.0.96.60.13.255": "mdi:flash-alert",
    "1.0.96.61.13.255": "mdi:timer-sand",
    "1.0.96.60.50.255": "mdi:alert-circle-outline",
}


class SensorDLMSMeterDiag(SensorDLMSMeter):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, dlmsmeter_param):
        super().__init__(coordinator, dlmsmeter_param)
        icon = _DIAG_ICONS.get(dlmsmeter_param["meter_param"])
        if icon is not None:
            self._attr_icon = icon

class SensorDLMSMeterDiagInfo(SensorDLMSMeterDiag):
    pass

class SensorDLMSMeterModelConfig(SensorDLMSMeterDiagInfo):
    """Model Config; state stays the raw order code, decoded fields go in attributes."""

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        model = None
        if data:
            for item in data:
                if item.get("meter_param") == _MODEL_OBIS:
                    model = item.get("value")
                    break
        return decode_model_config(model, self.native_value)

class SensorDLMSMeterDiagCounter(SensorDLMSMeterDiag, SensorDLMSMeterCounter):
    # Lifetime event counts; base Counter stays MEASUREMENT for live-cycle entities.
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

class SensorDLMSMeterDiagTimeDuration(SensorDLMSMeterDiag, SensorDLMSMeterTimeDuration):
    # Lifetime cumulative seconds; base TimeDuration intentionally has no state class.
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

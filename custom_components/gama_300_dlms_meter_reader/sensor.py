"""Platform for sensor integration."""
from datetime import datetime

from homeassistant.const import EntityCategory

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
    SensorEntity
)

from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from .const import build_unique_id
# Re-exported for backward compatibility: these used to live in this module.
from .coordinator import (  # noqa: F401
    DLMSMeterConfigCoordinator,
    DLMSMeterDataCoordinator,
    _attempt_reconnect,
    _ReconnectThrottle,
)
from .model_config import decode_model_config
from .problem_logic import compute_voltage_snapshot

import logging
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    runtime = config_entry.runtime_data
    hub = runtime.hub
    coordinator = runtime.coordinator
    coordinator_diag = runtime.coordinator_diag

    new_devices = []
    for dlmsmeter in hub.meters:
        new_devices.append(SensorDLMSMeterConnection(dlmsmeter))
        new_devices.append(SensorDLMSMeterManufacturer(dlmsmeter))
        new_devices.append(SensorDLMSMeterModel(dlmsmeter))

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

    voltage_obis = runtime.capabilities.get("voltage_obis") or []
    if voltage_obis:
        new_devices.append(MinimumPhaseVoltageSensor(runtime, voltage_obis))
        new_devices.append(MaximumPhaseVoltageSensor(runtime, voltage_obis))

    if new_devices:
        async_add_entities(new_devices)


class SensorBase(CoordinatorEntity, SensorEntity):
    """Base entity backed by a DataUpdateCoordinator."""

    def __init__(self, coordinator, dlmsmeter_param):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self.hub=coordinator.hub
        self.dlmsmeter_param = dlmsmeter_param
        self._attr_unique_id = build_unique_id(self.hub.identity_key, dlmsmeter_param['meter_param'])


class SensorDLMSMeter(SensorBase):
    def __init__(self, coordinator, dlmsmeter_param):
        super().__init__(coordinator, dlmsmeter_param)
        self.meter_param=dlmsmeter_param["meter_param"]
        self._attr_name = f"{dlmsmeter_param['text']}"

        if self.hub.display_suffix:
            self._attr_name = f"{self._attr_name} ({self.hub.display_suffix})"

        if "unit" in dlmsmeter_param :
            self._attr_native_unit_of_measurement = dlmsmeter_param["unit"]

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return self.hub.build_device_info()

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
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.REACTIVE_POWER

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


class SensorDLMSMeterConnection(SensorEntity):
    """Diagnostic: current connection endpoint. A config value, not a live metric.

    Not a CoordinatorEntity on purpose: it must stay available even while
    every DLMS poll is failing, since it shows where the integration is
    configured to connect, not whether that connection currently works.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lan-connect"
    _attr_should_poll = False

    def __init__(self, dlmsmeter):
        self.hub = dlmsmeter.hub
        self._attr_unique_id = build_unique_id(self.hub.identity_key, "connection")
        self._attr_name = "Connection"
        if self.hub.display_suffix:
            self._attr_name = f"{self._attr_name} ({self.hub.display_suffix})"

    @property
    def device_info(self):
        return self.hub.build_device_info()

    @property
    def native_value(self):
        return self.hub.endpoint_label


class SensorDLMSMeterManufacturer(SensorEntity):
    """Diagnostic: resolved manufacturer name. Cached metadata, not a live metric.

    Not a CoordinatorEntity on purpose: it must stay available even while
    every DLMS poll is failing. The state is whatever DeviceInfo shows, or
    None when that name is omitted (Home Assistant then reports unknown).
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:factory"
    _attr_should_poll = False

    def __init__(self, dlmsmeter):
        self.hub = dlmsmeter.hub
        self._attr_unique_id = build_unique_id(self.hub.identity_key, "manufacturer")
        self._attr_name = "Manufacturer"
        if self.hub.display_suffix:
            self._attr_name = f"{self._attr_name} ({self.hub.display_suffix})"

    @property
    def device_info(self):
        return self.hub.build_device_info()

    @property
    def native_value(self):
        return self.hub.manufacturer_name


class SensorDLMSMeterModel(SensorEntity):
    """Diagnostic: resolved model name, such as GAMA 300. Cached metadata.

    Not a CoordinatorEntity on purpose: it must stay available even while
    every DLMS poll is failing. The raw model-id register stays a separate
    sensor (Model ID); this one is the catalog name DeviceInfo already shows,
    or None when that name is omitted.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:meter-electric"
    _attr_should_poll = False

    def __init__(self, dlmsmeter):
        self.hub = dlmsmeter.hub
        self._attr_unique_id = build_unique_id(self.hub.identity_key, "model")
        self._attr_name = "Model"
        if self.hub.display_suffix:
            self._attr_name = f"{self._attr_name} ({self.hub.display_suffix})"

    @property
    def device_info(self):
        return self.hub.build_device_info()

    @property
    def native_value(self):
        return self.hub.model_name


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


class _VoltageAggregateSensor(CoordinatorEntity, SensorEntity):
    """Shared base for the two voltage extrema sensors.

    Primary measurement entities (no entity_category), backed by the live
    coordinator like any other measurement -- unlike the three fail-safe
    binary sensors, these follow the standard unavailable-on-failed-poll
    convention. The Voltage problem/Grid outage binary sensors use the same
    compute_voltage_snapshot() helper so all four never disagree.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = "V"
    _attr_has_entity_name = True

    def __init__(self, runtime, translation_key, unique_suffix, expected_obis):
        super().__init__(runtime.coordinator)
        self._runtime = runtime
        self._expected_obis = tuple(expected_obis)
        self._attr_translation_key = translation_key
        self._attr_unique_id = build_unique_id(runtime.hub.identity_key, unique_suffix)

    @property
    def device_info(self):
        return self._runtime.hub.build_device_info()

    def _snapshot(self):
        return compute_voltage_snapshot(self.coordinator.data, self._expected_obis)


class MinimumPhaseVoltageSensor(_VoltageAggregateSensor):
    def __init__(self, runtime, expected_obis):
        super().__init__(runtime, "minimum_phase_voltage", "minimum_phase_voltage", expected_obis)

    @property
    def native_value(self):
        if not self.coordinator.last_update_success:
            return None
        return self._snapshot().minimum


class MaximumPhaseVoltageSensor(_VoltageAggregateSensor):
    def __init__(self, runtime, expected_obis):
        super().__init__(runtime, "maximum_phase_voltage", "maximum_phase_voltage", expected_obis)

    @property
    def native_value(self):
        if not self.coordinator.last_update_success:
            return None
        return self._snapshot().maximum

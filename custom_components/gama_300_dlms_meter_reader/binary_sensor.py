"""Diagnostic problem BinarySensorEntities derived from the live coordinator.

Every entity here is created only if its source OBIS is present in the
capability snapshot (see runtime.capabilities); none of them do their own
DLMS I/O -- they all read the same live coordinator sample sensor.py's
measurement sensors already use.
"""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    OBIS_POWER_L1,
    OBIS_POWER_L2,
    OBIS_POWER_L3,
    OBIS_POWER_TOTAL,
    build_unique_id,
)
from .problem_logic import (
    compute_voltage_snapshot,
    frequency_problem,
    grid_outage_transition,
    normalize_measurement,
    overload_transition,
    value_for_obis,
    voltage_problem_transition,
)

_LOGGER = logging.getLogger(__name__)

# (translation_key, unique_suffix, source OBIS, thresholds field for the limit)
_PHASE_OVERLOAD_SPECS = (
    ("phase_l1_overload", "phase_l1_overload", OBIS_POWER_L1, "phase_l1_max_power_w"),
    ("phase_l2_overload", "phase_l2_overload", OBIS_POWER_L2, "phase_l2_max_power_w"),
    ("phase_l3_overload", "phase_l3_overload", OBIS_POWER_L3, "phase_l3_max_power_w"),
)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add the Diagnostic problem indicators this meter's capabilities support."""
    runtime = config_entry.runtime_data
    caps = runtime.capabilities
    entities: list[BinarySensorEntity] = []

    if caps.get("frequency_obis"):
        entities.append(FrequencyProblemBinarySensor(runtime))

    voltage_obis = caps.get("voltage_obis") or []
    if voltage_obis:
        entities.append(VoltageProblemBinarySensor(runtime, voltage_obis))
        entities.append(GridOutageBinarySensor(runtime, voltage_obis))

    active_power_obis = caps.get("active_power_obis") or []
    for translation_key, unique_suffix, obis, limit_key in _PHASE_OVERLOAD_SPECS:
        if obis in active_power_obis:
            entities.append(
                PhaseOverloadBinarySensor(runtime, translation_key, unique_suffix, obis, limit_key)
            )
    if OBIS_POWER_TOTAL in active_power_obis:
        entities.append(TotalOverloadBinarySensor(runtime))

    if entities:
        async_add_entities(entities)


class _ProblemBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Shared machinery for all seven Diagnostic problem indicators.

    HA's standard convention is to go unavailable when a coordinator update
    fails. By deliberate domain decision for this deployment, the three
    fail-safe indicators (frequency/voltage/grid outage) instead stay
    available and report On on a failed live poll, because here a lost
    TCP/serial/DLMS session is, in practice, almost always the meter losing
    its own power -- the one case those three exist to signal. This can
    false-positive on an unrelated gateway/cable failure; that trade-off is
    intentional, see the task notes, and must not be "fixed" by a future
    refactor back to the standard behaviour.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _fail_safe = False
    _use_latch = False

    def __init__(self, runtime, translation_key: str, unique_suffix: str) -> None:
        super().__init__(runtime.coordinator)
        self._runtime = runtime
        self._attr_translation_key = translation_key
        self._attr_unique_id = build_unique_id(runtime.hub.identity_key, unique_suffix)
        self._latched = False
        self._current_state: bool | None = None
        self._recompute(reset_latch=True)
        remove = runtime.add_settings_listener(self._on_settings_changed)
        self.async_on_remove(remove)

    @property
    def device_info(self):
        return self._runtime.hub.build_device_info()

    @property
    def available(self) -> bool:
        if self._fail_safe:
            return True
        return self.coordinator.last_update_success

    @property
    def is_on(self):
        if not self.coordinator.last_update_success:
            # Cached data is never used here: the failure itself is the signal.
            return True if self._fail_safe else None
        return self._current_state

    def _handle_coordinator_update(self) -> None:
        self._recompute(reset_latch=False)
        super()._handle_coordinator_update()

    def _on_settings_changed(self) -> None:
        # Threshold-only update: re-evaluate the cached sample against the
        # new thresholds, trigger-only (no carried-over latch), no new poll.
        self._recompute(reset_latch=True)
        self.async_write_ha_state()

    def _recompute(self, *, reset_latch: bool) -> None:
        if not self.coordinator.last_update_success:
            if self._fail_safe and self._use_latch:
                # A failed poll is itself treated as a proven problem for
                # these fail-safe indicators (is_on already reports On via
                # the failure branch below); latch it so recovery has to
                # cross the hysteresis boundary once polling succeeds again,
                # not just clear on the first value inside the deadband.
                self._latched = True
                return
            # Otherwise (plain overload sensors) a failed poll proves
            # nothing; keep whatever latch/displayed state already existed.
            return
        prior_latch = False if reset_latch else self._latched
        result = self._evaluate(prior_latch)
        if not self._use_latch:
            self._current_state = result
            return
        if result is None:
            # Missing/invalid value on an otherwise-successful poll: show
            # unknown this cycle without touching the confirmed latch.
            self._current_state = None
            return
        self._latched = result
        self._current_state = result

    def _evaluate(self, latched: bool) -> bool | None:
        raise NotImplementedError


class FrequencyProblemBinarySensor(_ProblemBinarySensor):
    """Stateless: the user did not ask for frequency hysteresis/debounce."""

    _fail_safe = True

    def __init__(self, runtime) -> None:
        self._obis = runtime.capabilities["frequency_obis"][0]
        super().__init__(runtime, "frequency_problem", "frequency_problem")

    def _evaluate(self, latched: bool) -> bool | None:
        value = normalize_measurement(value_for_obis(self.coordinator.data, self._obis))
        thresholds = self._runtime.thresholds
        return frequency_problem(value, thresholds.frequency_min_hz, thresholds.frequency_max_hz)


class VoltageProblemBinarySensor(_ProblemBinarySensor):
    _fail_safe = True
    _use_latch = True

    def __init__(self, runtime, expected_obis) -> None:
        self._expected_obis = tuple(expected_obis)
        super().__init__(runtime, "voltage_problem", "voltage_problem")

    def _evaluate(self, latched: bool) -> bool | None:
        snapshot = compute_voltage_snapshot(self.coordinator.data, self._expected_obis)
        thresholds = self._runtime.thresholds
        return voltage_problem_transition(
            latched, snapshot, thresholds.voltage_min_v, thresholds.voltage_max_v, thresholds.voltage_hysteresis_v
        )


class GridOutageBinarySensor(_ProblemBinarySensor):
    _fail_safe = True
    _use_latch = True

    def __init__(self, runtime, expected_obis) -> None:
        self._expected_obis = tuple(expected_obis)
        super().__init__(runtime, "grid_outage", "grid_outage")

    def _evaluate(self, latched: bool) -> bool | None:
        snapshot = compute_voltage_snapshot(self.coordinator.data, self._expected_obis)
        thresholds = self._runtime.thresholds
        return grid_outage_transition(latched, snapshot, thresholds.grid_outage_voltage_v, thresholds.voltage_hysteresis_v)


class PhaseOverloadBinarySensor(_ProblemBinarySensor):
    _use_latch = True

    def __init__(self, runtime, translation_key, unique_suffix, obis, limit_key) -> None:
        self._obis = obis
        self._limit_key = limit_key
        super().__init__(runtime, translation_key, unique_suffix)

    def _evaluate(self, latched: bool) -> bool | None:
        value = normalize_measurement(value_for_obis(self.coordinator.data, self._obis))
        thresholds = self._runtime.thresholds
        limit = getattr(thresholds, self._limit_key)
        return overload_transition(latched, value, limit, thresholds.power_hysteresis_w)


class TotalOverloadBinarySensor(_ProblemBinarySensor):
    _use_latch = True

    def __init__(self, runtime) -> None:
        super().__init__(runtime, "total_power_overload", "total_power_overload")

    def _evaluate(self, latched: bool) -> bool | None:
        value = normalize_measurement(value_for_obis(self.coordinator.data, OBIS_POWER_TOTAL))
        thresholds = self._runtime.thresholds
        return overload_transition(latched, value, thresholds.total_max_power_w, thresholds.power_hysteresis_w)

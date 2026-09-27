"""Pure validator and immutable resolved-settings model for the 11 threshold
and hysteresis entry.options keys shared by Configuration NumberEntities and
the Diagnostic problem binary_sensors.

No HA/DLMS imports here on purpose: this is used from setup, from
NumberEntity.async_set_native_value(), and from tests, and must behave
identically in all three.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from .const import (
    OPT_FREQUENCY_MAX_HZ,
    OPT_FREQUENCY_MIN_HZ,
    OPT_GRID_OUTAGE_VOLTAGE_V,
    OPT_PHASE_L1_MAX_POWER_W,
    OPT_PHASE_L2_MAX_POWER_W,
    OPT_PHASE_L3_MAX_POWER_W,
    OPT_POWER_HYSTERESIS_W,
    OPT_TOTAL_MAX_POWER_W,
    OPT_VOLTAGE_HYSTERESIS_V,
    OPT_VOLTAGE_MAX_V,
    OPT_VOLTAGE_MIN_V,
    THRESHOLD_DEFAULTS,
)


class ThresholdValidationError(ValueError):
    """Pure validation failure. Callers map translation_key/placeholders onto
    a localized homeassistant.exceptions.ServiceValidationError themselves;
    this module never imports Home Assistant."""

    def __init__(self, translation_key: str, placeholders: dict[str, str] | None = None) -> None:
        super().__init__(translation_key)
        self.translation_key = translation_key
        self.placeholders = placeholders or {}


@dataclass(frozen=True)
class ResolvedThresholds:
    """One immutable, fully validated snapshot of all 11 settings."""

    frequency_min_hz: float
    frequency_max_hz: float
    voltage_min_v: float
    voltage_max_v: float
    grid_outage_voltage_v: float
    voltage_hysteresis_v: float
    phase_l1_max_power_w: float
    phase_l2_max_power_w: float
    phase_l3_max_power_w: float
    total_max_power_w: float
    power_hysteresis_w: float


def _to_finite_float(value: Any, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ThresholdValidationError("invalid_number", {"key": key})
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise ThresholdValidationError("invalid_number", {"key": key})
    return number


def validate_thresholds(candidate: Mapping[str, Any]) -> ResolvedThresholds:
    """Validate and coerce the full 11-key set. Always resolves the complete
    set (missing keys fall back to defaults) -- callers must pass a merged
    copy of entry.options, never a partial update."""
    values: dict[str, float] = {
        key: _to_finite_float(candidate.get(key, default), key)
        for key, default in THRESHOLD_DEFAULTS.items()
    }

    f_min = values[OPT_FREQUENCY_MIN_HZ]
    f_max = values[OPT_FREQUENCY_MAX_HZ]
    if not (0 < f_min < f_max <= 100):
        raise ThresholdValidationError("invalid_frequency_range")

    v_outage = values[OPT_GRID_OUTAGE_VOLTAGE_V]
    v_min = values[OPT_VOLTAGE_MIN_V]
    v_max = values[OPT_VOLTAGE_MAX_V]
    if not (0 <= v_outage < v_min < v_max <= 500):
        raise ThresholdValidationError("invalid_voltage_range")

    v_hyst = values[OPT_VOLTAGE_HYSTERESIS_V]
    if v_hyst < 0 or v_outage + v_hyst > v_min or 2 * v_hyst >= v_max - v_min:
        raise ThresholdValidationError("invalid_voltage_hysteresis")

    power_limits = (
        values[OPT_PHASE_L1_MAX_POWER_W],
        values[OPT_PHASE_L2_MAX_POWER_W],
        values[OPT_PHASE_L3_MAX_POWER_W],
        values[OPT_TOTAL_MAX_POWER_W],
    )
    for limit in power_limits:
        if not (math.isfinite(limit) and limit > 0):
            raise ThresholdValidationError("invalid_power_limit")

    p_hyst = values[OPT_POWER_HYSTERESIS_W]
    if p_hyst < 0 or p_hyst >= min(power_limits):
        raise ThresholdValidationError("invalid_power_hysteresis")

    return ResolvedThresholds(**values)


def merge_and_validate(
    options: Mapping[str, Any], updates: Mapping[str, Any]
) -> tuple[dict[str, Any], ResolvedThresholds]:
    """Copy options, apply updates, validate the whole set. Never mutates options."""
    merged = dict(options)
    merged.update(updates)
    resolved = validate_thresholds(merged)
    return merged, resolved

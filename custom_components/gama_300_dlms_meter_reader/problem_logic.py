"""Pure helpers for the frequency/voltage/outage/overload problem indicators.

No HA/DLMS/coordinator imports: every function here takes already-read
values and already-resolved thresholds and returns a plain bool/None. This
is what table-driven tests exercise directly, and what binary_sensor.py (and
the two voltage aggregate sensors) call from coordinator-update time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


def normalize_measurement(raw: Any) -> float | None:
    """A live DLMS value -> float, or None if it cannot prove anything.

    Rejects bool (a distinct type from a real measurement), non-numeric
    types, and non-finite (NaN/inf) results -- treated as missing/invalid,
    never as a coincidentally huge or tiny reading.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if not math.isfinite(value):
        return None
    return value


def value_for_obis(data: Sequence[Mapping[str, Any]] | None, obis: str) -> Any:
    """Raw value for one OBIS in a coordinator's read_all_data()-shaped list."""
    if not data:
        return None
    for item in data:
        if item.get("meter_param") == obis:
            return item.get("value")
    return None


@dataclass(frozen=True)
class VoltageSnapshot:
    """Extrema over exactly the phases this meter is expected to report.

    Shared by the two voltage aggregate sensors and the Voltage
    problem/Grid outage binary sensors so they never disagree with each
    other about what "current voltage" means.
    """

    values_by_obis: Mapping[str, float]
    minimum: float | None
    maximum: float | None


_EMPTY_SNAPSHOT = VoltageSnapshot({}, None, None)


def compute_voltage_snapshot(
    data: Sequence[Mapping[str, Any]] | None, expected_obis: Sequence[str]
) -> VoltageSnapshot:
    """Extrema of the expected phase voltages on one successful poll.

    Any single expected phase missing, non-numeric, or non-finite makes the
    whole snapshot None/None: never computed from a random subset of phases.
    """
    if not expected_obis:
        return _EMPTY_SNAPSHOT

    values: dict[str, float] = {}
    for obis in expected_obis:
        normalized = normalize_measurement(value_for_obis(data, obis))
        if normalized is None:
            return _EMPTY_SNAPSHOT
        values[obis] = normalized

    return VoltageSnapshot(values, min(values.values()), max(values.values()))


def frequency_problem(frequency: float | None, min_hz: float, max_hz: float) -> bool | None:
    """Stateless: the user never asked for frequency hysteresis/debounce."""
    if frequency is None:
        return None
    return not (min_hz <= frequency <= max_hz)


def voltage_problem_transition(
    latched: bool,
    snapshot: VoltageSnapshot,
    min_v: float,
    max_v: float,
    hysteresis_v: float,
) -> bool | None:
    """Pure trigger/recovery transition; does not mutate anything itself."""
    if snapshot.minimum is None or snapshot.maximum is None:
        return None
    if latched:
        recovered = snapshot.minimum >= min_v + hysteresis_v and snapshot.maximum <= max_v - hysteresis_v
        return not recovered
    return snapshot.minimum < min_v or snapshot.maximum > max_v


def grid_outage_transition(
    latched: bool,
    snapshot: VoltageSnapshot,
    outage_v: float,
    hysteresis_v: float,
) -> bool | None:
    """Outage is the whole expected phase set below outage_v -- driven by the
    snapshot maximum: if any expected phase is still above it, no outage."""
    if snapshot.maximum is None:
        return None
    if latched:
        recovered = snapshot.maximum >= outage_v + hysteresis_v
        return not recovered
    return snapshot.maximum < outage_v


def overload_transition(
    latched: bool,
    power_w: float | None,
    limit_w: float,
    hysteresis_w: float,
) -> bool | None:
    """Shared by the three phase overloads and the total overload.

    abs(power_w): the configured limit is a conductor/load limit that
    matters in both import and export direction, not signed net power.
    """
    if power_w is None:
        return None
    magnitude = abs(power_w)
    if latched:
        recovered = magnitude <= limit_w - hysteresis_w
        return not recovered
    return magnitude > limit_w

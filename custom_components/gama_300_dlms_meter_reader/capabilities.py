"""Pure helpers for the entry.data hardware capability snapshot.

The snapshot is discovered hardware metadata (which OBIS groups this exact
meter answers for), not a user setting. No HA/DLMS imports: callers pass an
already-fetched set of available OBIS strings.
"""
from __future__ import annotations

from typing import Any, Iterable

from .const import (
    ACTIVE_POWER_OBIS_ORDER,
    CAPABILITY_SNAPSHOT_SCHEMA_VERSION,
    OBIS_FREQUENCY,
    VOLTAGE_OBIS_ORDER,
)

_SNAPSHOT_KEYS = ("frequency_obis", "voltage_obis", "active_power_obis")


def discover_capabilities(available_obis: Iterable[str]) -> dict[str, Any]:
    """Build a capability snapshot from a set of OBIS strings.

    Used both for the live association view (online setup/reconfigure) and
    for a legacy entry's own entity registry (offline capability inference)
    -- the two sources are just different ways to obtain the same set.
    """
    available = set(available_obis)
    return {
        "version": CAPABILITY_SNAPSHOT_SCHEMA_VERSION,
        "frequency_obis": [OBIS_FREQUENCY] if OBIS_FREQUENCY in available else [],
        "voltage_obis": sorted(obis for obis in VOLTAGE_OBIS_ORDER if obis in available),
        "active_power_obis": sorted(obis for obis in ACTIVE_POWER_OBIS_ORDER if obis in available),
    }


def is_valid_snapshot(snapshot: Any) -> bool:
    """True for a well-formed, current-schema snapshot; False for anything
    else (missing, malformed, or an unknown/future schema version) -- callers
    fall back to registry inference rather than trusting a bad snapshot."""
    if not isinstance(snapshot, dict):
        return False
    if snapshot.get("version") != CAPABILITY_SNAPSHOT_SCHEMA_VERSION:
        return False
    for key in _SNAPSHOT_KEYS:
        value = snapshot.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return False
    return True

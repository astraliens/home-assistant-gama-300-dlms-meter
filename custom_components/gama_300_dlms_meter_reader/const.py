from dataclasses import dataclass

# This is the internal name of the integration, it should also match the directory
# name for the integration.
DOMAIN = "gama_300_dlms_meter_reader"

# entry.data key: host as it was before the first reconfigure that changed it.
# Device name, entity IP-suffix and entry title keep using this so reconfigure
# never renames anything a user already sees.
CONF_DISPLAY_HOST = "display_host"

# entry.options keys for the two coordinators (see config_flow.OptionsFlowHandler).
OPT_SCAN_INTERVAL = "scan_interval"
OPT_DIAG_SCAN_INTERVAL = "diag_scan_interval"

# Matches the hardcoded behavior this replaces; changing the default changes
# every existing install that never opened Options.
DEFAULT_SCAN_INTERVAL = 3
MIN_SCAN_INTERVAL = 3
MAX_SCAN_INTERVAL = 3600

DEFAULT_DIAG_SCAN_INTERVAL = 600
MIN_DIAG_SCAN_INTERVAL = 60
MAX_DIAG_SCAN_INTERVAL = 86400


def build_unique_id(serial, meter_param: str) -> str:
    """Entity unique_id. Tied to the meter, not its address, so it survives host/port changes."""
    return f"dlms_meter_{serial}_{meter_param}"


def build_device_identifier(serial) -> tuple[str, str]:
    """Device registry identifier for the meter."""
    return (DOMAIN, str(serial))


def build_meter_unique_id(serial) -> str:
    """Stable config-entry unique_id: the meter identity, independent of host/port."""
    return f"meter:{serial}"


def build_entry_unique_id(host: str, port: int, serial) -> str:
    """Pre-1.3 endpoint-based unique_id. Superseded by build_meter_unique_id; kept
    only for the 1.1 -> 1.2 legacy migration step and its dedupe checks."""
    return f"{host}:{port}:{serial}"


# --- OBIS codes used to derive/discover binary_sensor + aggregate sensor sources ---
OBIS_FREQUENCY = "1.0.14.7.0.255"
OBIS_VOLTAGE_L1 = "1.0.32.7.0.255"
OBIS_VOLTAGE_L2 = "1.0.52.7.0.255"
OBIS_VOLTAGE_L3 = "1.0.72.7.0.255"
OBIS_POWER_L1 = "1.0.36.7.0.255"
OBIS_POWER_L2 = "1.0.56.7.0.255"
OBIS_POWER_L3 = "1.0.76.7.0.255"
OBIS_POWER_TOTAL = "1.0.16.7.0.255"

VOLTAGE_OBIS_ORDER = (OBIS_VOLTAGE_L1, OBIS_VOLTAGE_L2, OBIS_VOLTAGE_L3)
ACTIVE_POWER_OBIS_ORDER = (OBIS_POWER_TOTAL, OBIS_POWER_L1, OBIS_POWER_L2, OBIS_POWER_L3)

# Every OBIS a legacy-entry capability backfill is allowed to infer from this
# entry's own existing sensor entities (see __init__._infer_capabilities_from_registry).
CAPABILITY_TRACKED_OBIS = frozenset({OBIS_FREQUENCY, *VOLTAGE_OBIS_ORDER, *ACTIVE_POWER_OBIS_ORDER})

# entry.data key: immutable hardware capability snapshot discovered at install/
# reconfigure time (see ai_info task spec); never user-editable, never thresholds.
CONF_CAPABILITIES = "capabilities"
CAPABILITY_SNAPSHOT_SCHEMA_VERSION = 1

# --- The 11 threshold/hysteresis entry.options keys (Configuration NumberEntities) ---
OPT_FREQUENCY_MIN_HZ = "frequency_min_hz"
OPT_FREQUENCY_MAX_HZ = "frequency_max_hz"
OPT_VOLTAGE_MIN_V = "voltage_min_v"
OPT_VOLTAGE_MAX_V = "voltage_max_v"
OPT_GRID_OUTAGE_VOLTAGE_V = "grid_outage_voltage_v"
OPT_VOLTAGE_HYSTERESIS_V = "voltage_hysteresis_v"
OPT_PHASE_L1_MAX_POWER_W = "phase_l1_max_power_w"
OPT_PHASE_L2_MAX_POWER_W = "phase_l2_max_power_w"
OPT_PHASE_L3_MAX_POWER_W = "phase_l3_max_power_w"
OPT_TOTAL_MAX_POWER_W = "total_max_power_w"
OPT_POWER_HYSTERESIS_W = "power_hysteresis_w"

THRESHOLD_DEFAULTS: dict[str, float] = {
    OPT_FREQUENCY_MIN_HZ: 49.75,
    OPT_FREQUENCY_MAX_HZ: 50.25,
    OPT_VOLTAGE_MIN_V: 200.0,
    OPT_VOLTAGE_MAX_V: 245.0,
    OPT_GRID_OUTAGE_VOLTAGE_V: 150.0,
    OPT_VOLTAGE_HYSTERESIS_V: 4.0,
    OPT_PHASE_L1_MAX_POWER_W: 7000.0,
    OPT_PHASE_L2_MAX_POWER_W: 7000.0,
    OPT_PHASE_L3_MAX_POWER_W: 7000.0,
    OPT_TOTAL_MAX_POWER_W: 14000.0,
    OPT_POWER_HYSTERESIS_W: 500.0,
}


@dataclass(frozen=True)
class NumberSetting:
    """Native range for one Configuration NumberEntity; key doubles as its translation_key."""

    key: str
    min_value: float
    max_value: float
    step: float
    unit: str
    icon: str


# Upper power bounds are deliberately very wide: NumberEntity needs a finite
# native range, but the real limit is the cross-field validator in thresholds.py,
# not this selector -- transformer/installation sizing varies too much for a
# fixed narrow cap to make sense here.
NUMBER_SETTINGS: tuple[NumberSetting, ...] = (
    NumberSetting(OPT_FREQUENCY_MIN_HZ, 0.01, 100.0, 0.01, "Hz", "mdi:arrow-collapse-down"),
    NumberSetting(OPT_FREQUENCY_MAX_HZ, 0.01, 100.0, 0.01, "Hz", "mdi:arrow-collapse-up"),
    NumberSetting(OPT_VOLTAGE_MIN_V, 0.0, 500.0, 1.0, "V", "mdi:arrow-collapse-down"),
    NumberSetting(OPT_VOLTAGE_MAX_V, 0.0, 500.0, 1.0, "V", "mdi:arrow-collapse-up"),
    NumberSetting(OPT_GRID_OUTAGE_VOLTAGE_V, 0.0, 500.0, 1.0, "V", "mdi:power-plug-off"),
    NumberSetting(OPT_VOLTAGE_HYSTERESIS_V, 0.0, 500.0, 0.1, "V", "mdi:delta"),
    NumberSetting(OPT_PHASE_L1_MAX_POWER_W, 1.0, 1_000_000_000.0, 100.0, "W", "mdi:numeric-1-circle"),
    NumberSetting(OPT_PHASE_L2_MAX_POWER_W, 1.0, 1_000_000_000.0, 100.0, "W", "mdi:numeric-2-circle"),
    NumberSetting(OPT_PHASE_L3_MAX_POWER_W, 1.0, 1_000_000_000.0, 100.0, "W", "mdi:numeric-3-circle"),
    NumberSetting(OPT_TOTAL_MAX_POWER_W, 1.0, 1_000_000_000.0, 100.0, "W", "mdi:sigma"),
    NumberSetting(OPT_POWER_HYSTERESIS_W, 0.0, 1_000_000_000.0, 100.0, "W", "mdi:delta"),
)

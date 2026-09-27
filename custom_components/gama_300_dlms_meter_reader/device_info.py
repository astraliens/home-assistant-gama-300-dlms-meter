"""Pure DeviceInfo builder shared by all entity platforms.

No I/O here: callers pass already-cached, already-read values (the
normalized LDN manufacturer FLAG ID and the raw config OBIS strings) and get
back a DeviceInfo dict. The bundled catalog is the only file this module
touches, and only once (see _load_catalog below).
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

_CATALOG_PATH = Path(__file__).parent / "dlms_read_data" / "dlms_device_catalog.json"
_ALLOWED_ROOT_KEYS = {"schema_version", "manufacturers", "model_matchers"}
_SUPPORTED_SCHEMA_VERSION = 1

# Vendors whose 1.0.96.1.2.255 is a hardware/order configuration code safe to
# surface as hw_version. Not a general OBIS->field rule: adding a vendor here
# is a deliberate per-vendor decision, not something the catalog JSON grants.
_HW_VERSION_FLAG_IDS = frozenset({"EGM"})


def _empty_catalog() -> tuple[dict[str, str], list[dict[str, str]]]:
    return {}, []


def _validate_manufacturers(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("manufacturers must be an object")
    result: dict[str, str] = {}
    for flag_id, name in value.items():
        if not isinstance(flag_id, str) or len(flag_id) != 3 or not flag_id.isalpha():
            raise ValueError(f"invalid manufacturer FLAG ID key: {flag_id!r}")
        if not isinstance(name, str) or not name:
            raise ValueError(f"invalid manufacturer name for {flag_id!r}")
        result[flag_id] = name
    return result


def _validate_model_matchers(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("model_matchers must be an array")
    result = []
    for matcher in value:
        if not isinstance(matcher, dict) or set(matcher) != {
            "flag_id",
            "match",
            "value",
            "model",
        }:
            raise ValueError(f"invalid model matcher shape: {matcher!r}")
        if matcher["match"] != "prefix":
            raise ValueError(f"unsupported matcher kind: {matcher['match']!r}")
        if not all(isinstance(matcher[key], str) and matcher[key] for key in matcher):
            raise ValueError(f"invalid model matcher values: {matcher!r}")
        result.append(matcher)
    return result


@lru_cache(maxsize=1)
def _load_catalog() -> tuple[dict[str, str], list[dict[str, str]]]:
    """Load and strictly validate the bundled catalog once per process.

    Any problem (missing file, bad JSON, wrong schema version, unexpected
    key, planning-only data) falls back to an empty catalog: manufacturer
    then shows as the raw FLAG ID and model is omitted, but setup never
    fails because of this asset.
    """
    try:
        raw = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) != _ALLOWED_ROOT_KEYS:
            raise ValueError(f"unexpected root keys: {sorted(raw) if isinstance(raw, dict) else raw!r}")
        if raw["schema_version"] != _SUPPORTED_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {raw['schema_version']!r}")
        manufacturers = _validate_manufacturers(raw["manufacturers"])
        model_matchers = _validate_model_matchers(raw["model_matchers"])
    except Exception:  # pylint: disable=broad-except
        _LOGGER.error(
            "Bundled device catalog is missing or invalid; manufacturer/model "
            "lookup will fall back to raw codes",
            exc_info=True,
        )
        return _empty_catalog()
    return manufacturers, model_matchers


def preload_catalog() -> None:
    """Populate the catalog cache now, off the event loop.

    build_device_info() (via resolve_manufacturer()/resolve_model()) would
    otherwise do this filesystem read lazily on whatever call happens first,
    typically an entity's device_info property accessed synchronously in the
    event loop during platform setup. Call this once from an executor job
    during config entry setup, before any entity is added.
    """
    _load_catalog()


def _extract_bytes(value: Any) -> bytes | None:
    """bytes-like -> bytes, without the repr/hex risk of a bare str(value)."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    array_method = getattr(value, "array", None)
    if callable(array_method):
        try:
            return bytes(array_method())
        except Exception:  # pylint: disable=broad-except
            return None
    return None


def normalize_ldn_flag_id(raw: Any) -> str | None:
    """First three ASCII letters of a logical device name, canonicalized to uppercase.

    Returns None for anything that is not confidently a FLAG ID: wrong type,
    undecodable bytes, too short, non-letters, or control characters.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, str):
        text = raw
    else:
        data = _extract_bytes(raw)
        if data is None:
            return None
        try:
            text = data.decode("ascii")
        except UnicodeDecodeError:
            return None

    text = text.strip().rstrip("\x00").strip()
    if len(text) < 3:
        return None
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in text):
        return None
    prefix = text[:3]
    if not prefix.isascii() or not prefix.isalpha():
        return None
    return prefix.upper()


def normalize_config_value(raw: Any) -> str | None:
    """Config OBIS value -> a clean str, or None for empty/invalid input."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (bytes, bytearray)):
        try:
            text = bytes(raw).decode("ascii")
        except UnicodeDecodeError:
            return None
    elif isinstance(raw, str):
        text = raw
    else:
        return None
    text = text.strip().rstrip("\x00").strip()
    return text or None


def resolve_manufacturer(flag_id: str | None) -> str | None:
    """Catalog display name for an unambiguous FLAG ID; raw code otherwise."""
    if not flag_id:
        return None
    manufacturers, _ = _load_catalog()
    return manufacturers.get(flag_id, flag_id)


def resolve_model(flag_id: str | None, model_id: str | None) -> str | None:
    """Model name from a runtime-enabled matcher scoped to flag_id, or None."""
    if not flag_id or not model_id:
        return None
    _, model_matchers = _load_catalog()
    for matcher in model_matchers:
        if matcher["flag_id"] != flag_id:
            continue
        if matcher["match"] == "prefix" and model_id.startswith(matcher["value"]):
            return matcher["model"]
    return None


def resolve_hw_version(flag_id: str | None, hw_config_raw: Any) -> str | None:
    """Normalized 1.0.96.1.2.255, only for vendors with an explicit opt-in."""
    if flag_id not in _HW_VERSION_FLAG_IDS:
        return None
    return normalize_config_value(hw_config_raw)


def build_device_info(
    *,
    identifiers: set[tuple[str, str]],
    name: str,
    flag_id: str | None,
    model_id_raw: Any = None,
    hw_config_raw: Any = None,
    serial_number_raw: Any = None,
    sw_version_raw: Any = None,
) -> dict[str, Any]:
    """Pure DeviceInfo builder. Optional keys are omitted, never None.

    identifiers/name are passed through unchanged (registry identity is not
    this module's concern). Everything else is derived only from the given
    cached values, so the result does not depend on read order or timing.
    """
    info: dict[str, Any] = {"identifiers": identifiers, "name": name}

    manufacturer = resolve_manufacturer(flag_id)
    if manufacturer:
        info["manufacturer"] = manufacturer

    model_id = normalize_config_value(model_id_raw)
    if model_id:
        info["model_id"] = model_id

    model = resolve_model(flag_id, model_id)
    if model:
        info["model"] = model

    serial_number = normalize_config_value(serial_number_raw)
    if serial_number:
        info["serial_number"] = serial_number

    sw_version = normalize_config_value(sw_version_raw)
    if sw_version:
        info["sw_version"] = sw_version

    hw_version = resolve_hw_version(flag_id, hw_config_raw)
    if hw_version:
        info["hw_version"] = hw_version

    return info

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from . import hub
from .capabilities import discover_capabilities, is_valid_snapshot
from .const import (
    CAPABILITY_TRACKED_OBIS,
    CONF_CAPABILITIES,
    CONF_DISPLAY_HOST,
    DEFAULT_DIAG_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OPT_DIAG_SCAN_INTERVAL,
    OPT_SCAN_INTERVAL,
    build_device_identifier,
    build_entry_unique_id,
    build_meter_unique_id,
    build_unique_id,
)
from .coordinator import DLMSMeterConfigCoordinator, DLMSMeterDataCoordinator, _ReconnectThrottle
from .device_info import preload_catalog
from .runtime import GamaRuntimeData
from .thresholds import ThresholdValidationError, validate_thresholds

PLATFORMS: list[str] = ["sensor", "number", "binary_sensor"]

_LOGGER = logging.getLogger(__name__)


def _migration_data(entry: ConfigEntry) -> tuple[str, int, int, str] | None:
    """Return validated legacy connection data when it is safe to migrate."""
    host = entry.data.get("host")
    port = entry.data.get("port")
    serial = entry.data.get("serial")

    if (
        not isinstance(host, str)
        or len(host) < 3
        or host != host.strip()
    ):
        return None
    if (
        isinstance(port, bool)
        or not isinstance(port, int)
        or not 1 <= port <= 65535
    ):
        return None
    if (
        isinstance(serial, bool)
        or not isinstance(serial, int)
        or serial <= 0
    ):
        return None

    entity_type = entry.data.get("entity_type")
    if entity_type is None or entity_type == "":
        normalized_entity_type = "default"
    elif isinstance(entity_type, str):
        normalized_entity_type = entity_type.lower()
    else:
        return None
    if normalized_entity_type not in {"default", "ip", "serial"}:
        return None

    return host, port, serial, normalized_entity_type


def _old_identity(entity_type: str, host: str, serial: int) -> str:
    """Identity value entities/device were keyed on before serial-based identity."""
    if entity_type == "serial":
        return str(serial)
    return host.lower()


async def _migrate_entities_to_serial(
    hass: HomeAssistant, entry: ConfigEntry, old_identity: str, serial: int
) -> None:
    """Rewrite entity unique_ids to the serial-based scheme, entity_id untouched.

    async_migrate_entries() has no built-in collision handling: an unguarded
    ValueError from one entity aborts every entity after it, with nothing already
    applied rolled back. The callback must check and skip, never raise.
    """
    ent_reg = er.async_get(hass)
    old_prefix = f"dlms_meter_{old_identity}_"

    def _entry_callback(entity: er.RegistryEntry) -> dict | None:
        if entity.unique_id is None or not entity.unique_id.startswith(old_prefix):
            return None
        meter_param = entity.unique_id[len(old_prefix):]
        new_unique_id = build_unique_id(serial, meter_param)
        if new_unique_id == entity.unique_id:
            return None
        conflict = ent_reg.async_get_entity_id(entity.domain, entity.platform, new_unique_id)
        if conflict:
            _LOGGER.warning(
                "Skipping identity migration for %s: unique_id %s is already used by %s",
                entity.entity_id,
                new_unique_id,
                conflict,
            )
            return None
        return {"new_unique_id": new_unique_id}

    await er.async_migrate_entries(hass, entry.entry_id, _entry_callback)


def _devices_with_identifier(dev_reg, identifier: tuple[str, str]) -> list:
    """Return every device owning an identifier across supported HA versions."""
    async_get_devices = getattr(dev_reg, "async_get_devices", None)
    if callable(async_get_devices):
        return list(async_get_devices(identifiers={identifier}))

    device = dev_reg.async_get_device(identifiers={identifier})
    return [] if device is None else [device]


def _migrate_device_to_serial(
    hass: HomeAssistant, entry: ConfigEntry, old_identity: str, serial: int
) -> None:
    """Point the existing device entry at the new identifier; never create a second device."""
    dev_reg = dr.async_get(hass)
    legacy_identifier = (DOMAIN, old_identity)
    devices = [
        device
        for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
        if legacy_identifier in device.identifiers
    ]
    if len(devices) != 1:
        _LOGGER.warning(
            "Skipping device identity migration for config entry %s: "
            "expected one associated device, found %d",
            entry.entry_id,
            len(devices),
        )
        return

    device = devices[0]
    if device.config_entries != {entry.entry_id}:
        _LOGGER.warning(
            "Skipping device identity migration for %s: device is shared by %d "
            "config entries",
            device.id,
            len(device.config_entries),
        )
        return

    target_identifier = build_device_identifier(serial)
    new_identifiers = (
        device.identifiers - {legacy_identifier}
    ) | {target_identifier}
    if new_identifiers == device.identifiers:
        return

    for other_device in _devices_with_identifier(dev_reg, target_identifier):
        if other_device.id != device.id:
            _LOGGER.warning(
                "Skipping device identity migration for %s: identifier is already "
                "used by %s",
                device.id,
                other_device.id,
            )
            return

    try:
        dev_reg.async_update_device(device.id, new_identifiers=new_identifiers)
    except dr.DeviceIdentifierCollisionError:
        _LOGGER.warning(
            "Skipping device identity migration for %s: identifier already in use",
            device.id,
        )


def _backfill_entry_unique_id(
    hass: HomeAssistant, entry: ConfigEntry, host: str, port: int, serial: int
) -> None:
    """Set entry.unique_id for entries created before it existed (pre-1.2 scheme).

    Superseded by _migrate_unique_id_to_meter_key() below, which runs right
    after this in the same migration pass and moves the entry off this
    endpoint-based value onto the stable meter key.
    """
    if entry.unique_id is not None:
        return

    candidate = build_entry_unique_id(host, port, serial)
    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id != entry.entry_id and other.unique_id == candidate:
            _LOGGER.warning(
                "Not setting unique_id for entry %s: %s is already used by another entry",
                entry.entry_id, candidate,
            )
            return

    hass.config_entries.async_update_entry(entry, unique_id=candidate)


def _migrate_unique_id_to_meter_key(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Point entry.unique_id at the stable meter:{serial} key.

    Idempotent preflight: a no-op if already on the target key. On a genuine
    collision with another entry, skip and warn without mutating either entry
    -- the caller still advances minor_version so this entry stays loadable.
    Not retried automatically on a later start once minor_version has moved
    past this step; resolving the collision (e.g. removing the duplicate
    entry) does not by itself re-trigger this backfill.
    """
    serial = entry.data.get("serial")
    if isinstance(serial, bool) or not isinstance(serial, int) or serial <= 0:
        _LOGGER.warning(
            "Skipping meter identity migration for config entry %s: missing or "
            "invalid serial",
            entry.entry_id,
        )
        return

    candidate = build_meter_unique_id(serial)
    if entry.unique_id == candidate:
        return

    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id != entry.entry_id and other.unique_id == candidate:
            _LOGGER.warning(
                "Skipping meter identity migration for config entry %s: %s is "
                "already used by another entry",
                entry.entry_id, candidate,
            )
            return

    hass.config_entries.async_update_entry(entry, unique_id=candidate)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Move entity/device/entry identity off the host, onto the meter serial.

    Runs before platforms are forwarded; HA guarantees that order and will not
    crash on an unhandled exception here, but that alone does not protect
    against unique_id collisions -- this function's own checks do.
    Rolling back to a version without this migration is not supported: the old
    code recreates entities/device under the pre-migration keys with no history.

    Two chained minor_version steps: 1 -> 2 moves entity/device unique_ids from
    the pre-serial host-based scheme; 2 -> 3 moves the config entry's own
    unique_id from the endpoint-based scheme to the stable meter key. Both run
    in the same call for a fresh legacy entry so a single migration pass lands
    it on the current scheme.
    """
    if entry.version != 1:
        return True

    if entry.minor_version == 1:
        migration_data = _migration_data(entry)
        if migration_data is None:
            _LOGGER.error(
                "Cannot migrate config entry %s: invalid host, port, serial, or "
                "entity type",
                entry.entry_id,
            )
            return False

        host, port, serial, entity_type = migration_data
        old_identity = _old_identity(entity_type, host, serial)

        await _migrate_entities_to_serial(hass, entry, old_identity, serial)
        _migrate_device_to_serial(hass, entry, old_identity, serial)
        _backfill_entry_unique_id(hass, entry, host, port, serial)

        hass.config_entries.async_update_entry(entry, version=1, minor_version=2)

    if entry.minor_version == 2:
        _migrate_unique_id_to_meter_key(hass, entry)
        hass.config_entries.async_update_entry(entry, version=1, minor_version=3)

    return True


def _should_nudge_diag_coordinator(
    *, live_success: bool, diag_success: bool, already_nudged: bool
) -> tuple[bool, bool]:
    """Pure edge-trigger decision for the diagnostic recovery nudge.

    Without this latch, a live coordinator succeeding every few seconds
    while the diagnostic session keeps failing on its own would re-request
    a diagnostic refresh on every single live success, forcing it to the
    live cadence instead of leaving it bounded to at most one extra read
    per outage. Returns (should_nudge_now, next "already_nudged" state);
    the caller is responsible for actually requesting the refresh.
    """
    if not live_success:
        return False, False
    if diag_success or already_nudged:
        return False, already_nudged
    return True, True


def _capability_fingerprint(snapshot: Any) -> tuple | None:
    """Reload-relevant shape of a capability snapshot; None for anything invalid
    (a malformed snapshot alone should not by itself trigger a reload loop)."""
    if not is_valid_snapshot(snapshot):
        return None
    return (
        tuple(snapshot.get("frequency_obis", [])),
        tuple(snapshot.get("voltage_obis", [])),
        tuple(snapshot.get("active_power_obis", [])),
    )


def _lifecycle_fingerprint(entry: ConfigEntry) -> tuple:
    """Values that require a reload when they change.

    Everything else in entry.options (the 11 threshold/hysteresis settings)
    is deliberately excluded so those updates can be applied live without a
    reload -- see the threshold-only branch in _make_lifecycle_listener.
    """
    return (
        entry.data.get("host"),
        entry.data.get("port"),
        entry.data.get("serial"),
        entry.data.get(CONF_DISPLAY_HOST),
        _capability_fingerprint(entry.data.get(CONF_CAPABILITIES)),
        entry.options.get(OPT_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        entry.options.get(OPT_DIAG_SCAN_INTERVAL, DEFAULT_DIAG_SCAN_INTERVAL),
    )


def _make_lifecycle_listener(entry: ConfigEntry, runtime: GamaRuntimeData | None = None):
    """Build a one-shot update listener that reloads only on a real lifecycle change.

    The fingerprint is captured now, at setup, and compared against the entry's
    state whenever HA calls the returned listener later. Registering a fresh
    listener on every setup (and removing it via entry.async_on_unload) is what
    keeps this to exactly one listener, and one reload, per relevant change.

    When runtime is given, a change confined to the 11 threshold/hysteresis
    options is applied live instead: the resolved settings are swapped
    atomically and every subscribed number/binary_sensor entity is notified,
    with no reload and no new DLMS poll.
    """
    initial_fingerprint = _lifecycle_fingerprint(entry)

    async def _listener(hass: HomeAssistant, updated_entry: ConfigEntry) -> None:
        if _lifecycle_fingerprint(updated_entry) != initial_fingerprint:
            await hass.config_entries.async_reload(updated_entry.entry_id)
            return

        if runtime is None:
            return

        try:
            new_thresholds = validate_thresholds(updated_entry.options)
        except ThresholdValidationError:
            _LOGGER.warning(
                "Ignoring invalid threshold options for config entry %s",
                updated_entry.entry_id,
                exc_info=True,
            )
            return

        if new_thresholds != runtime.thresholds:
            runtime.update_thresholds(new_thresholds)

    return _listener


def _infer_capabilities_from_registry(hass: HomeAssistant, entry: ConfigEntry) -> dict | None:
    """Legacy-entry capability recovery from this entry's own entity registry.

    Scoped to this config entry's own sensor unique_ids so a never-loaded
    legacy entry with no evidence at all still falls through to None (and
    from there to ConfigEntryNotReady) instead of inventing entities.
    """
    serial = entry.data.get("serial")
    if isinstance(serial, bool) or not isinstance(serial, int):
        return None

    prefix = f"dlms_meter_{serial}_"
    ent_reg = er.async_get(hass)
    present: set[str] = set()
    for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if entity.domain != "sensor" or entity.unique_id is None:
            continue
        if not entity.unique_id.startswith(prefix):
            continue
        obis = entity.unique_id[len(prefix):]
        if obis in CAPABILITY_TRACKED_OBIS:
            present.add(obis)

    if not present:
        return None
    return discover_capabilities(present)


async def _resolve_capabilities(
    hass: HomeAssistant, entry: ConfigEntry, meter_hub: hub.Hub, *, connected: bool
) -> dict | None:
    """The capability snapshot to use for this setup, or None if unknown.

    Online: always re-derived from the live association view -- the most
    trustworthy source, and the only one that can grow/shrink correctly.
    Offline: trust an already-stored snapshot; otherwise fall back to this
    entry's own entity registry; otherwise unknown (caller must not invent
    entities -- see the ConfigEntryNotReady branch in async_setup_entry).
    """
    if connected:
        return await hass.async_add_executor_job(meter_hub.discover_capabilities)

    stored = entry.data.get(CONF_CAPABILITIES)
    if is_valid_snapshot(stored):
        return stored
    if stored is not None:
        _LOGGER.warning(
            "Ignoring malformed capability snapshot for config entry %s",
            entry.entry_id,
        )

    return _infer_capabilities_from_registry(hass, entry)


def _maybe_persist_capability_snapshot(
    hass: HomeAssistant, entry: ConfigEntry, capabilities: dict
) -> None:
    """Only write entry.data when the derived snapshot actually changed.

    Always runs before the update listener is registered (see
    async_setup_entry), so this can never trigger a reload of the entry
    currently being set up.
    """
    if entry.data.get(CONF_CAPABILITIES) == capabilities:
        return
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_CAPABILITIES: capabilities}
    )


async def _cleanup_failed_setup(hass: HomeAssistant, entry: ConfigEntry, meter_hub: hub.Hub) -> None:
    """Remove the hub from hass.data and permanently retire its session.

    A coordinator that got far enough to be created before a later platform
    failed still has its shutdown-on-unload hook registered; close() (not
    plain disconnect()) makes sure that if its poll timer fires before that
    hook runs, it fails fast instead of reconnecting an instance nothing
    owns anymore.
    """
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    entry.runtime_data = None
    try:
        await hass.async_add_executor_job(meter_hub.close)
    except Exception:
        _LOGGER.debug("Closing session after failed platform setup also failed", exc_info=True)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Connect the meter session (best-effort), then set up platforms.

    A connect failure does not necessarily abort setup: if this entry's
    hardware capabilities are already known (a stored snapshot, or -- for a
    legacy entry -- inferred from its own entity registry), setup continues
    offline so the three fail-safe problem indicators can come up as
    available + On instead of the whole device disappearing during an
    outage. Only a genuinely unknown entry (never loaded, no evidence at
    all) still raises ConfigEntryNotReady.
    """
    entity_type = entry.data.get("entity_type") or ""
    display_host = entry.data.get(CONF_DISPLAY_HOST)

    meter_hub = hub.Hub(
        hass,
        entry.data["host"],
        entry.data["port"],
        entry.data["serial"],
        entity_type,
        display_host=display_host,
    )

    # Off the event loop and independent of connect: device_info.py's catalog
    # lookup would otherwise do this file read lazily, the first time any
    # entity's device_info property is accessed while forwarding platforms.
    await hass.async_add_executor_job(preload_catalog)

    connect_error: Exception | None = None
    try:
        await hass.async_add_executor_job(meter_hub.connect)
    except Exception as err:  # pylint: disable=broad-except
        connect_error = err

    capabilities = await _resolve_capabilities(
        hass, entry, meter_hub, connected=connect_error is None
    )
    if capabilities is None:
        try:
            await hass.async_add_executor_job(meter_hub.close)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.debug("Closing session after a failed setup also failed", exc_info=True)
        raise ConfigEntryNotReady(
            f"Could not connect to meter at {entry.data['host']}"
        ) from connect_error

    # Before the update listener exists, so this can never self-trigger a reload.
    _maybe_persist_capability_snapshot(hass, entry, capabilities)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = meter_hub

    reconnect_throttle = _ReconnectThrottle()
    scan_interval = entry.options.get(OPT_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    diag_scan_interval = entry.options.get(OPT_DIAG_SCAN_INTERVAL, DEFAULT_DIAG_SCAN_INTERVAL)

    coordinator = DLMSMeterDataCoordinator(
        hass, meter_hub, reconnect_throttle, scan_interval, config_entry=entry
    )
    coordinator_diag = DLMSMeterConfigCoordinator(
        hass, meter_hub, reconnect_throttle, diag_scan_interval, config_entry=entry
    )

    if connect_error is None:
        # Online: abort setup like before if even the first real read fails.
        await coordinator.async_config_entry_first_refresh()
        await coordinator_diag.async_config_entry_first_refresh()
    else:
        # Offline-known: record the failed state now (last_update_success
        # becomes False) without aborting. Both coordinators still get their
        # next bounded update scheduled once the first entity subscribes --
        # DataUpdateCoordinator.async_add_listener() schedules a refresh for
        # the first listener regardless of the outcome of this one.
        await coordinator.async_refresh()
        await coordinator_diag.async_refresh()

    try:
        resolved_thresholds = validate_thresholds(entry.options)
    except ThresholdValidationError:
        _LOGGER.warning(
            "Invalid threshold options for config entry %s; using defaults",
            entry.entry_id,
            exc_info=True,
        )
        resolved_thresholds = validate_thresholds({})

    runtime = GamaRuntimeData(
        hub=meter_hub,
        coordinator=coordinator,
        coordinator_diag=coordinator_diag,
        thresholds=resolved_thresholds,
        capabilities=capabilities,
    )
    entry.runtime_data = runtime

    diag_recovery_state = {"nudged": False}

    def _nudge_diag_coordinator_on_recovery() -> None:
        """Fast-path diagnostic recovery, at most once per outage.

        The diagnostic sensors would otherwise stay unavailable for up to
        its own (much longer, default 600s) interval after the meter comes
        back. Piggyback on the live coordinator's first success after a
        failure instead of polling faster -- MeterClient serializes actual
        reads on its own lock, so this can never race a read already in
        flight on the same session.

        Stands down once this entry starts unloading or the session has
        been permanently retired, since nothing then owns the read this
        would schedule.
        """
        if runtime.shutting_down or meter_hub.closed:
            return
        should_nudge, diag_recovery_state["nudged"] = _should_nudge_diag_coordinator(
            live_success=coordinator.last_update_success,
            diag_success=coordinator_diag.last_update_success,
            already_nudged=diag_recovery_state["nudged"],
        )
        if should_nudge:
            hass.async_create_task(
                coordinator_diag.async_request_refresh(),
                f"{DOMAIN} diagnostic coordinator recovery refresh",
            )

    entry.async_on_unload(coordinator.async_add_listener(_nudge_diag_coordinator_on_recovery))

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await _cleanup_failed_setup(hass, entry, meter_hub)
        raise
    except asyncio.CancelledError:
        await _cleanup_failed_setup(hass, entry, meter_hub)
        raise

    entry.async_on_unload(
        entry.add_update_listener(_make_lifecycle_listener(entry, runtime))
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms, then permanently retire the meter session.

    The coordinators created in this module's async_setup_entry register
    their own shutdown with entry.async_on_unload, but that fires only after this
    function returns -- their poll timers are still armed for the whole
    duration of this call. close() (not plain disconnect()) makes any such
    poll's next read fail fast instead of silently reconnecting this exact
    instance to an endpoint this entry no longer owns.
    """
    # getattr, not entry.runtime_data: this can run for an entry whose setup
    # never got far enough to assign it (e.g. a cleanup path in tests).
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None:
        # Before anything else: stands down the diagnostic recovery nudge
        # for the whole remainder of teardown, not just after hub.close().
        runtime.shutting_down = True

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        meter_hub = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if meter_hub is not None:
            await hass.async_add_executor_job(meter_hub.close)

    return unload_ok

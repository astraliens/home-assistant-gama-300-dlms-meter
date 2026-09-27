"""Per-config-entry runtime shared by every platform.

One Hub, one pair of coordinators, the currently resolved thresholds and the
hardware capability snapshot -- created once in __init__.async_setup_entry()
before platforms are forwarded, and reached by sensor/number/binary_sensor
through ConfigEntry.runtime_data. Kept free of HA imports beyond typing so it
stays trivial to unit test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .thresholds import ResolvedThresholds


@dataclass
class GamaRuntimeData:
    hub: Any
    coordinator: Any
    coordinator_diag: Any
    thresholds: ResolvedThresholds
    capabilities: dict[str, Any]
    _listeners: list[Callable[[], None]] = field(default_factory=list, repr=False)
    # Set at the very start of async_unload_entry(), before platforms unload
    # or the hub session closes -- lets anything scheduled off a coordinator
    # listener (see the diagnostic recovery nudge in __init__.py) opt out of
    # firing into a teardown already in progress.
    shutting_down: bool = False

    def add_settings_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to threshold-only updates. Returns an unsubscribe callable
        for entities to pass to Entity.async_on_remove()."""
        self._listeners.append(callback)

        def _remove() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return _remove

    def update_thresholds(self, new_thresholds: ResolvedThresholds) -> None:
        """Atomically swap the resolved thresholds and notify every subscriber.

        No DLMS poll, no reload: entities react by resetting their latch and
        re-evaluating the current coordinator sample (see binary_sensor.py).
        """
        self.thresholds = new_thresholds
        for callback in list(self._listeners):
            callback()

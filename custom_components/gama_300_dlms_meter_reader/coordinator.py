"""Shared DataUpdateCoordinators: one live, one diagnostic, per config entry.

Created once in __init__.async_setup_entry() and reached by every platform
through ConfigEntry.runtime_data, so there is exactly one poll loop against
the meter no matter how many platforms subscribe to it. Moved out of
sensor.py so binary_sensor.py (and number.py's no-poll entities) can use the
same live coordinator without a second concurrent Gurux session.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

# Bounds a single reconnect attempt, symmetric with the 30s/20s read timeouts
# below. Without this, a reconnect that never returns (a hung executor job --
# e.g. tearing down a half-broken transport) would stall this coordinator's
# refresh, and with it every future poll on the shared session/lock/throttle,
# indefinitely instead of failing like any other bounded outage.
_RECONNECT_TIMEOUT = 30


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
    """Executor reconnect; only CancelledError can escape.

    asyncio.shield() keeps the underlying executor job (and the
    MeterClient._lock it may be holding) running to completion even if this
    wait times out or this coroutine itself gets cancelled -- only the wait
    is cancelled here, not the job. The throttle is released from the job's
    own done-callback once it actually finishes, not from this function
    directly: releasing it early, while the job may still be running and
    holding the lock, would let a later failed poll queue a second
    reconnect job behind the same lock instead of failing fast as "reconnect
    already in progress".
    """
    if not throttle.claim_attempt():
        return

    released = False

    def _release(job) -> None:
        nonlocal released
        if released:
            return
        released = True
        throttle.release(not job.cancelled() and job.exception() is None)

    job = hass.async_add_executor_job(hub.reconnect)
    job.add_done_callback(_release)
    try:
        async with asyncio.timeout(_RECONNECT_TIMEOUT):
            await asyncio.shield(job)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        _LOGGER.debug(
            "Reconnect attempt timed out; still running in the background",
            exc_info=True,
        )
    except Exception:
        _LOGGER.debug("Reconnect attempt failed", exc_info=True)


class DLMSMeterDataCoordinator(DataUpdateCoordinator):
    """Coordinator for the fast-changing measurement data."""

    def __init__(self, hass, hub, reconnect_throttle, scan_interval, config_entry=None):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="Meter Data Coordinator",
            update_interval=timedelta(seconds=scan_interval),
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

    def __init__(self, hass, hub, reconnect_throttle, diag_scan_interval, config_entry=None):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="Meter Config Coordinator",
            update_interval=timedelta(seconds=diag_scan_interval),
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

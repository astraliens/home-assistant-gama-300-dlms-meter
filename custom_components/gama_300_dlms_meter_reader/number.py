"""Configuration NumberEntities for the 11 threshold/hysteresis settings.

Offline-capable and read-only towards the meter: native_value reads the
already-validated ResolvedThresholds from the shared runtime; setting a new
value only ever writes entry.options through async_update_entry(). No entity
here ever opens a DLMS session or blocks on coordinator state.
"""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN, NUMBER_SETTINGS, build_unique_id
from .thresholds import ThresholdValidationError, merge_and_validate

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add the 11 Configuration number entities for passed config_entry."""
    runtime = config_entry.runtime_data
    entities = [
        GamaConfigNumber(config_entry, runtime, spec) for spec in NUMBER_SETTINGS
    ]
    async_add_entities(entities)


class GamaConfigNumber(NumberEntity):
    """One threshold/hysteresis setting, shown under the device's Configuration block."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, config_entry, runtime, spec) -> None:
        self._config_entry = config_entry
        self._runtime = runtime
        self._key = spec.key
        self._attr_translation_key = spec.key
        self._attr_unique_id = build_unique_id(runtime.hub.identity_key, f"config_{spec.key}")
        self._attr_native_min_value = spec.min_value
        self._attr_native_max_value = spec.max_value
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_icon = spec.icon
        remove = runtime.add_settings_listener(self._on_settings_changed)
        self.async_on_remove(remove)

    @property
    def device_info(self):
        return self._runtime.hub.build_device_info()

    @property
    def available(self) -> bool:
        # Settings are plain options, not live meter data: always available
        # for a loaded entry, connection failure included.
        return True

    @property
    def native_value(self) -> float:
        return getattr(self._runtime.thresholds, self._key)

    def _on_settings_changed(self) -> None:
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        try:
            merged_options, _resolved = merge_and_validate(
                self._config_entry.options, {self._key: value}
            )
        except ThresholdValidationError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=err.translation_key,
                translation_placeholders=err.placeholders,
            ) from err
        self.hass.config_entries.async_update_entry(
            self._config_entry, options=merged_options
        )

"""Bluetooth signal strength (RSSI) sensor, fed from the controller's advertisements."""
from __future__ import annotations

import time

from homeassistant.components import bluetooth
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import CONF_ADDRESS, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LedDmxConfigEntry
from .entity import LedDmxEntity

# The controller advertises every ~60 ms; don't write a state for each one.
MIN_UPDATE_INTERVAL = 30.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LedDmxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([LedDmxRssi(entry)])


class LedDmxRssi(LedDmxEntity, SensorEntity):
    _attr_translation_key = "rssi"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_assumed_state = False

    def __init__(self, entry: LedDmxConfigEntry) -> None:
        super().__init__(entry)
        self._address = entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{self._address}_rssi"
        self._last_write = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if info := bluetooth.async_last_service_info(self.hass, self._address, connectable=False):
            self._apply(info)
        self.async_on_remove(
            bluetooth.async_register_callback(
                self.hass,
                self._on_advertisement,
                bluetooth.BluetoothCallbackMatcher(address=self._address),
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        )

    def _apply(self, info: bluetooth.BluetoothServiceInfoBleak) -> None:
        self._attr_native_value = info.rssi
        self._attr_extra_state_attributes = {"source": info.source}
        self._last_write = time.monotonic()

    @callback
    def _on_advertisement(
        self,
        info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        first = self._attr_native_value is None
        due = time.monotonic() - self._last_write >= MIN_UPDATE_INTERVAL
        moved = (self._attr_extra_state_attributes or {}).get("source") != info.source
        if first or due or moved:
            self._apply(info)
            self.async_write_ha_state()

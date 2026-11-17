"""Effect speed number entity for LEDDMX controllers."""
from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LedDmxConfigEntry
from . import protocol as p
from .entity import LedDmxEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LedDmxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([LedDmxSpeed(entry)])


class LedDmxSpeed(LedDmxEntity, RestoreNumber):
    _attr_translation_key = "effect_speed"
    _attr_icon = "mdi:speedometer"
    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry: LedDmxConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.data[CONF_ADDRESS]}_speed"
        self._attr_native_value = 50

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) is not None and last.native_value:
            self._attr_native_value = last.native_value

    async def async_set_native_value(self, value: float) -> None:
        await self._device.send(p.speed(int(value)))
        self._attr_native_value = int(value)
        self.async_write_ha_state()

"""Light entity for LEDDMX controllers.

The controller never reports state, so this entity is optimistic: it remembers
what it last sent (and restores that across HA restarts).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    EFFECT_OFF,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoredExtraData, RestoreEntity

from . import LedDmxConfigEntry
from . import protocol as p
from .effects import EFFECT_BY_NAME, EFFECTS
from .entity import LedDmxEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LedDmxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([LedDmxLight(entry)])


def _to_pct(brightness: int) -> int:
    """HA brightness 1-255 -> controller percent 1-100."""
    return max(1, min(100, round(brightness * 100 / 255)))


class LedDmxLight(LedDmxEntity, LightEntity, RestoreEntity):
    _attr_name = None  # the device name is the light name
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = [EFFECT_OFF, *EFFECTS.values()]

    def __init__(self, entry: LedDmxConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = entry.data[CONF_ADDRESS]
        self._attr_is_on = False
        self._attr_brightness = 255
        self._attr_rgb_color = (255, 255, 255)
        self._attr_effect = EFFECT_OFF

    # -- restore ----------------------------------------------------------------

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        # Saved even while off (HA drops color/brightness attributes for off lights).
        return RestoredExtraData(
            {
                "brightness": self._attr_brightness,
                "rgb_color": list(self._attr_rgb_color or (255, 255, 255)),
                "effect": self._attr_effect,
            }
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == "on"
        if (extra := await self.async_get_last_extra_data()) is not None:
            data = extra.as_dict()
            if isinstance(data.get("brightness"), int):
                self._attr_brightness = data["brightness"]
            if isinstance(data.get("rgb_color"), list) and len(data["rgb_color"]) == 3:
                self._attr_rgb_color = tuple(data["rgb_color"])
            if data.get("effect") in self._attr_effect_list:
                self._attr_effect = data["effect"]

    # -- control ----------------------------------------------------------------

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Observed on the device:
        #  - power-on while already on restarts the running animation, so only send it
        #    when we think it's off, or on a bare turn_on (lets the user recover after
        #    the remote switched it off behind our back);
        #  - a color frame resets brightness to 100 %, effect frames keep it.
        resync = not self._attr_is_on or not kwargs
        frames: list[bytes] = [p.power(True)] if resync else []
        send_brightness = resync or ATTR_BRIGHTNESS in kwargs

        effect = kwargs.get(ATTR_EFFECT)
        if effect is not None and effect != EFFECT_OFF:
            if effect not in EFFECT_BY_NAME:
                raise ValueError(f"Unknown effect {effect!r}")
            frames.append(p.effect(EFFECT_BY_NAME[effect]))
            self._attr_effect = effect
        elif ATTR_RGB_COLOR in kwargs or effect == EFFECT_OFF:
            rgb = kwargs.get(ATTR_RGB_COLOR, self._attr_rgb_color)
            frames.append(p.color(*rgb))
            self._attr_rgb_color = tuple(rgb)
            self._attr_effect = EFFECT_OFF
            send_brightness = True

        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
        if send_brightness:
            frames.append(p.brightness(_to_pct(self._attr_brightness)))

        await self._device.send(*frames)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.send(p.power(False))
        self._attr_is_on = False
        self.async_write_ha_state()

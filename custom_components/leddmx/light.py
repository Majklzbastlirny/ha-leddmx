"""Light entity for LEDDMX controllers.

The controller never reports state, so this entity is optimistic: it remembers
what it last sent (and restores that across HA restarts).

Brightness model (from observing the hardware):
  - static color: the controller's own brightness only has 32 steps and rounds
    small channels up, so at low brightness (255,1,0) turns visibly yellow. A
    color frame also resets controller brightness to 100 %. So for static colors
    we leave the controller at 100 % and scale the RGB ourselves (8-bit
    resolution), which is one frame per change and keeps hues true when dim.
  - effects: the animation colors come from the controller, so brightness must
    use the controller's brightness command (effect frames keep it).
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
from .const import CONF_GAMMA, DEFAULT_GAMMA
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


def scale_rgb(
    rgb: tuple[int, int, int], brightness: int, gamma: float = 1.0
) -> tuple[int, int, int]:
    """Apply optional per-channel gamma, then brightness, in 8-bit space."""
    if gamma != 1.0:
        rgb = tuple(round(255 * (c / 255) ** gamma) for c in rgb)
    factor = max(0, min(255, brightness)) / 255
    out = [round(c * factor) for c in rgb]
    if brightness > 0 and max(rgb) > 0 and max(out) == 0:
        # never render "on" as black: keep the dominant channel at the minimum step
        out[rgb.index(max(rgb))] = 1
    return tuple(out)


class LedDmxLight(LedDmxEntity, LightEntity, RestoreEntity):
    _attr_name = None  # the device name is the light name
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = [EFFECT_OFF, *EFFECTS.values()]

    def __init__(self, entry: LedDmxConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = entry.data[CONF_ADDRESS]
        self._gamma = float(entry.options.get(CONF_GAMMA, DEFAULT_GAMMA))
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

    def _color_frame(self) -> bytes:
        return p.color(*scale_rgb(self._attr_rgb_color, self._attr_brightness, self._gamma))

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Power-on while already on restarts the running animation, so only send it
        # when we think it's off, or on a bare turn_on (lets the user recover after
        # the remote switched it off behind our back).
        resync = not self._attr_is_on or not kwargs
        frames: list[bytes] = [p.power(True)] if resync else []

        effect = kwargs.get(ATTR_EFFECT)
        if effect is not None and effect != EFFECT_OFF and effect not in EFFECT_BY_NAME:
            raise ValueError(f"Unknown effect {effect!r}")
        new_brightness = ATTR_BRIGHTNESS in kwargs
        if new_brightness:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
        new_color = ATTR_RGB_COLOR in kwargs
        if new_color:
            self._attr_rgb_color = tuple(kwargs[ATTR_RGB_COLOR])

        new_effect = effect is not None and effect != EFFECT_OFF
        if new_effect:
            self._attr_effect = effect
        elif new_color or effect == EFFECT_OFF:
            self._attr_effect = EFFECT_OFF

        if self._attr_effect == EFFECT_OFF:
            # static color: one frame carries color and brightness
            if resync or new_color or new_brightness or effect == EFFECT_OFF:
                frames.append(self._color_frame())
        else:
            if new_effect or resync:
                frames.append(p.effect(EFFECT_BY_NAME[self._attr_effect]))
            # controller brightness may still be at 100 % from static mode
            if new_effect or resync or new_brightness:
                frames.append(p.brightness(_to_pct(self._attr_brightness)))

        await self._device.send(*frames)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.send(p.power(False))
        self._attr_is_on = False
        self.async_write_ha_state()

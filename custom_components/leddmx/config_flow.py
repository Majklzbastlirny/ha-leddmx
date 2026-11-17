"""Config flow for LEDDMX: Bluetooth discovery + manual pick from seen devices."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .const import (
    CONF_GAMMA,
    CONF_IDLE_TIMEOUT,
    DEFAULT_GAMMA,
    DEFAULT_IDLE_TIMEOUT,
    DOMAIN,
    NAME_PREFIX,
)

_ADV_UUID = "0000ffb0-0000-1000-8000-00805f9b34fb"


def _is_leddmx(info: BluetoothServiceInfoBleak) -> bool:
    name = info.name or ""
    return name.upper().startswith(NAME_PREFIX) or _ADV_UUID in info.service_uuids


class LedDmxConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._candidates: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address.upper())
        self._abort_if_unique_id_configured()
        if not _is_leddmx(discovery_info):
            return self.async_abort(reason="not_supported")
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name or discovery_info.address}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery is not None
        title = self._discovery.name or self._discovery.address
        if user_input is not None:
            return self.async_create_entry(
                title=title, data={CONF_ADDRESS: self._discovery.address.upper()}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm", description_placeholders={"name": title}
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS].upper()
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._candidates.get(address, address), data={CONF_ADDRESS: address}
            )

        configured = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            address = info.address.upper()
            if address in configured or not _is_leddmx(info):
                continue
            self._candidates[address] = info.name or address
        if not self._candidates:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {a: f"{n} ({a})" for a, n in self._candidates.items()}
                    )
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LedDmxOptionsFlow()


class LedDmxOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_IDLE_TIMEOUT, default=opts.get(CONF_IDLE_TIMEOUT, DEFAULT_IDLE_TIMEOUT)
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=3600)),
                    vol.Required(
                        CONF_GAMMA, default=opts.get(CONF_GAMMA, DEFAULT_GAMMA)
                    ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=3.0)),
                }
            ),
        )

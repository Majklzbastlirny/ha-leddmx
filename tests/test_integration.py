"""Config flow + entity behaviour, with Bluetooth and the BLE link mocked."""
from unittest.mock import AsyncMock, patch

from bleak.backends.device import BLEDevice
from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.leddmx import protocol as p
from custom_components.leddmx.const import DOMAIN
from custom_components.leddmx.light import scale_rgb

ADDR = "C0:00:00:00:00:79"
NAME = "LEDDMX-000079"
BLE = BLEDevice(ADDR, NAME, details=None)


def _info() -> BluetoothServiceInfoBleak:
    return BluetoothServiceInfoBleak(
        name=NAME,
        address=ADDR,
        rssi=-50,
        manufacturer_data={192: b"\x00\x00\x00\x79"},
        service_data={},
        service_uuids=["0000ffb0-0000-1000-8000-00805f9b34fb"],
        source="local",
        device=BLE,
        advertisement=None,
        connectable=True,
        time=0,
        tx_power=None,
    )


async def test_user_flow(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.leddmx.config_flow.async_discovered_service_info",
        return_value=[_info()],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        with patch("custom_components.leddmx.async_setup_entry", return_value=True):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_ADDRESS: ADDR}
            )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {CONF_ADDRESS: ADDR}


async def test_bluetooth_discovery_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"
    with patch("custom_components.leddmx.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == ADDR


def _patches(send):
    return (
        patch("custom_components.leddmx.bluetooth.async_ble_device_from_address", return_value=BLE),
        patch("custom_components.leddmx.bluetooth.async_register_callback", return_value=lambda: None),
        patch("custom_components.leddmx.bluetooth.async_last_service_info", return_value=_info()),
        patch("custom_components.leddmx.device.LedDmxDevice.send", send),
        patch("custom_components.leddmx.device.LedDmxDevice.disconnect", AsyncMock()),
    )


def test_scale_rgb() -> None:
    assert scale_rgb((255, 0, 0), 255) == (255, 0, 0)
    assert scale_rgb((255, 0, 0), 128) == (128, 0, 0)
    # the reported case: tiny green must vanish when dim instead of tinting yellow
    assert scale_rgb((255, 1, 0), 10) == (10, 0, 0)
    # never black while on
    assert scale_rgb((1, 0, 0), 1) == (1, 0, 0)
    assert scale_rgb((255, 128, 0), 255, gamma=2.2) == (255, 56, 0)
    assert scale_rgb((255, 1, 0), 255, gamma=2.2) == (255, 0, 0)


async def test_entities_send_expected_frames(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title=NAME, unique_id=ADDR, data={CONF_ADDRESS: ADDR})
    entry.add_to_hass(hass)
    send = AsyncMock()
    a, b, c, d, e = _patches(send)
    with a, b, c, d, e:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        light = "light.leddmx_000079"
        speed = "number.leddmx_000079_effect_speed"
        rssi = "sensor.leddmx_000079_signal_strength"
        for ent in (light, speed, rssi):
            assert hass.states.get(ent) is not None, hass.states.async_entity_ids()
        assert hass.states.get(rssi).state == "-50"
        assert hass.states.get(rssi).attributes["source"] == "local"

        async def turn_on(**data):
            await hass.services.async_call(
                "light", "turn_on", {"entity_id": light, **data}, blocking=True
            )

        # from off: power + one color frame with brightness applied in RGB
        await turn_on(rgb_color=[255, 0, 0], brightness=128)
        assert send.await_args.args == (p.power(True), p.color(128, 0, 0))
        st = hass.states.get(light)
        assert st.state == "on" and st.attributes["rgb_color"] == (255, 0, 0)
        assert st.attributes["effect"] == "off"

        # static brightness change = one color frame; tiny channels vanish when dim
        await turn_on(rgb_color=[255, 1, 0], brightness=10)
        assert send.await_args.args == (p.color(10, 0, 0),)
        await turn_on(brightness=128)
        assert send.await_args.args == (p.color(128, 1, 0),)

        # effect: no power frame (would restart animation), controller brightness follows
        await turn_on(effect="081 Gradual 7 Colors")
        assert send.await_args.args == (p.effect(81), p.brightness(50))
        assert hass.states.get(light).attributes["effect"] == "081 Gradual 7 Colors"

        await turn_on(effect="Auto cycle")
        assert send.await_args.args == (p.effect(255), p.brightness(50))

        await turn_on(brightness=255)
        assert send.await_args.args == (p.brightness(100),)

        # back to static color ("off" effect = remembered color)
        await turn_on(effect="off")
        assert send.await_args.args == (p.color(255, 1, 0),)

        await turn_on(rgb_color=[0, 0, 255])
        assert send.await_args.args == (p.color(0, 0, 255),)

        # bare turn_on while on = resync
        await turn_on()
        assert send.await_args.args == (p.power(True), p.color(0, 0, 255))

        await hass.services.async_call("light", "turn_off", {"entity_id": light}, blocking=True)
        assert send.await_args.args == (p.power(False),)
        assert hass.states.get(light).state == "off"

        # turning on from off into an effect: power, effect, brightness
        await turn_on(effect="003 Forward 7 Colors")
        assert send.await_args.args == (p.power(True), p.effect(3), p.brightness(100))

        await hass.services.async_call(
            "number", "set_value", {"entity_id": speed, "value": 80}, blocking=True
        )
        assert send.await_args.args == (p.speed(80),)

        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_options_gamma(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title=NAME, unique_id=ADDR, data={CONF_ADDRESS: ADDR})
    entry.add_to_hass(hass)
    send = AsyncMock()
    a, b, c, d, e = _patches(send)
    with a, b, c, d, e:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"idle_timeout": 30, "gamma": 2.2}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()  # entry reloads with new options
        await hass.services.async_call(
            "light", "turn_on",
            {"entity_id": "light.leddmx_000079", "rgb_color": [255, 128, 0], "brightness": 255},
            blocking=True,
        )
        assert send.await_args.args == (p.power(True), p.color(255, 56, 0))


async def test_not_ready_when_unseen(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title=NAME, unique_id=ADDR, data={CONF_ADDRESS: ADDR})
    entry.add_to_hass(hass)
    with patch(
        "custom_components.leddmx.bluetooth.async_ble_device_from_address", return_value=None
    ):
        await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is config_entries.ConfigEntryState.SETUP_RETRY

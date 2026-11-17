"""Exercise custom_components/leddmx/device.py against the real chain (no HA needed)."""
import asyncio
import importlib.machinery
import importlib.util
import logging
import pathlib
import sys
import time

from bleak import BleakScanner

# Load custom_components/leddmx as a package without running its HA-dependent __init__.py
PKG_DIR = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "leddmx"
pkg = importlib.util.module_from_spec(importlib.machinery.ModuleSpec("ldx", None, is_package=True))
pkg.__path__ = [str(PKG_DIR)]
sys.modules["ldx"] = pkg
from ldx import protocol as p  # noqa: E402
from ldx.device import LedDmxDevice  # noqa: E402

ADDR = "C0:00:00:00:00:79"


async def main() -> None:
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s.%(msecs)03d %(name)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("bleak", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    ble = await BleakScanner.find_device_by_address(ADDR, timeout=10)
    assert ble, "device not found"
    dev = LedDmxDevice(ble, idle_timeout=5)
    dev.add_connection_listener(lambda c: print(f"### connection -> {c}"))

    t = time.monotonic()
    await dev.send(p.power(True), p.color(0, 0, 255), p.brightness(60))
    print(f"### first send (incl. connect) {time.monotonic() - t:.2f}s")

    # simulate slider drag: 10 quick brightness steps over the open connection
    t = time.monotonic()
    for pct in range(60, 9, -5):
        await dev.send(p.brightness(pct))
    print(f"### 11 brightness steps on open connection {time.monotonic() - t:.2f}s")

    print("### waiting 7s for idle disconnect")
    await asyncio.sleep(7)
    assert not dev.connected, "should have idle-disconnected"

    t = time.monotonic()
    await dev.send(p.brightness(60), p.color(0, 255, 0))
    print(f"### send after idle reconnect {time.monotonic() - t:.2f}s")
    await dev.send(p.effect(81), p.speed(70))
    await dev.disconnect()
    print("### done, connected =", dev.connected)


asyncio.run(main())

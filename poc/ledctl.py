"""PoC CLI: connect once to the LED chain and run a sequence of commands.

Examples:
  python poc/ledctl.py off
  python poc/ledctl.py on color:255,0,0 wait:1 color:0,255,0
  python poc/ledctl.py raw:7bff0400ffffffffbf
  python poc/ledctl.py --handshake on bright:50
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
import leddmx as p  # noqa: E402

DEFAULT_ADDR = "C0:00:00:00:00:79"
GAP = 0.08  # seconds between writes (app throttles 30-50 ms)


def parse(cmd: str) -> bytes | float:
    name, _, arg = cmd.partition(":")
    args = [int(x, 0) for x in arg.split(",")] if arg and name != "raw" else []
    match name:
        case "on":
            return p.power(True)
        case "off":
            return p.power(False)
        case "on2":
            return p.power_alt(True)
        case "off2":
            return p.power_alt(False)
        case "color":
            return p.color(*args)
        case "bright":
            return p.brightness(args[0])
        case "mode":
            return p.mode(args[0])
        case "speed":
            return p.speed(*args)
        case "dir":
            return p.direction(args[0])
        case "pause":
            return p.pause(args[0])
        case "hs":
            return p.handshake()
        case "raw":
            return bytes.fromhex(arg.replace(" ", ""))
        case "wait":
            return float(arg or 1)
    raise SystemExit(f"unknown command: {cmd}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr", default=DEFAULT_ADDR)
    ap.add_argument("--handshake", action="store_true", help="send app's password/time frame first")
    ap.add_argument("--listen", type=float, default=1.0, help="seconds to wait for notifications at end")
    ap.add_argument("--gap", type=float, default=GAP, help="seconds between frames")
    ap.add_argument("--barrier", action="store_true", help="GATT read after each write (delivery barrier)")
    ap.add_argument("cmds", nargs="+")
    a = ap.parse_args()
    steps = [parse(c) for c in a.cmds]

    dev = await BleakScanner.find_device_by_address(a.addr, timeout=10.0)
    if dev is None:
        raise SystemExit(f"{a.addr} not found")
    t0 = time.monotonic()
    async with BleakClient(dev, timeout=20.0) as c:
        print(f"connected in {time.monotonic() - t0:.1f}s")

        def on_notify(_h, data: bytearray) -> None:
            print(f"  <- notify {data.hex(' ')}")

        await c.start_notify(p.CHAR_UUID, on_notify)
        if a.handshake:
            await asyncio.sleep(0.3)
            hs = p.handshake()
            print(f"  -> {hs.hex(' ')}  (handshake)")
            await c.write_gatt_char(p.CHAR_UUID, hs, response=False)
            await asyncio.sleep(0.3)
        for raw, step in zip(a.cmds, steps):
            if isinstance(step, float):
                await asyncio.sleep(step)
                continue
            print(f"  -> {step.hex(' ')}  ({raw})")
            await c.write_gatt_char(p.CHAR_UUID, step, response=False)
            if a.barrier:
                t = time.monotonic()
                await c.read_gatt_char(p.CHAR_UUID)
                print(f"     barrier {1000 * (time.monotonic() - t):.0f} ms")
            if a.gap:
                await asyncio.sleep(a.gap)
        await asyncio.sleep(a.listen)


asyncio.run(main())

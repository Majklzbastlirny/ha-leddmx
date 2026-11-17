"""Scan for LEDDMX devices and dump their GATT table."""
import asyncio
from bleak import BleakScanner, BleakClient


async def main():
    print("Scanning 8s...")
    found = await BleakScanner.discover(timeout=8.0, return_adv=True)
    target = None
    for addr, (dev, adv) in found.items():
        name = adv.local_name or dev.name or ""
        if "LED" in name.upper() or "ffb0" in " ".join(adv.service_uuids).lower():
            print(f"  {addr}  {name!r}  rssi={adv.rssi}  uuids={adv.service_uuids}  mfr={ {k: v.hex() for k, v in adv.manufacturer_data.items()} }")
            target = target or dev
    if not target:
        print("No LEDDMX device found")
        return
    print(f"\nConnecting to {target.address} ...")
    async with BleakClient(target, timeout=20.0) as client:
        for svc in client.services:
            print(f"[service] {svc.uuid}  {svc.description}")
            for ch in svc.characteristics:
                val = ""
                if "read" in ch.properties:
                    try:
                        val = (await client.read_gatt_char(ch)).hex()
                    except Exception as e:  # noqa: BLE001
                        val = f"<read err {e}>"
                print(f"   [char] {ch.uuid} h={ch.handle} props={ch.properties} {val}")
                for d in ch.descriptors:
                    print(f"      [desc] {d.uuid} h={d.handle}")


asyncio.run(main())

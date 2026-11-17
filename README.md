# LEDDMX BLE pixel controller for Home Assistant

Local Bluetooth control of the cheap addressable LED chains/strips sold with the
**LED LAMP** app whose controller advertises as `LEDDMX-xxxxxx` (AMICCOM chip,
advertised service `FFB0`, manufacturer id `0x00C0`). Tested with a 10 m / 100× WS2812
chain (`LEDDMX-000079`).

Works through any **connectable** Bluetooth path Home Assistant has: the host's own
adapter or ESPHome Bluetooth proxies with `active: true`. Passive-only scanners
(e.g. Shelly BLE gateways) can't be used: the controller has to be connected to and
written to over GATT, and it doesn't react to advertisements.

## Entities

| Entity | What it does |
|---|---|
| `light.leddmx_xxxxxx` | on/off, RGB color, brightness, 210 built-in effects + "Auto cycle" (`off` effect = back to static color) |
| `number.leddmx_xxxxxx_effect_speed` | animation speed 1–100 |

The controller never reports its state, so entities are **assumed state**. HA shows
what it last sent, and changes made with the IR/RF remote or the phone app aren't
reflected. If the remote switched it off while HA still shows it on, a plain
`light.turn_on` with no arguments re-sends power-on and brightness.

Quirks observed on the hardware, and handled by the integration:
- a color frame resets brightness to 100 %, so brightness is re-sent after every color change (effect frames keep it);
- power-on while already on restarts the running animation, so it's only sent when HA thinks the light is off;
- a frame is dropped when the next one arrives back-to-back, which happens easily through a proxy. Each write is
  followed by a GATT read of `FFE1`, a request/response that guarantees delivery before the next frame (~20–30 ms).

Only the `LEDDMX-01` frame variant is implemented. That's what the app uses for names like
`LEDDMX-000079` that don't match one of its typed prefixes. Names starting `LEDDMX-02-`, `-04-`, `-05-`
or `-06-` use a different framing in the app and will likely not work.

## Connection behaviour

A command opens a GATT connection, which stays open while more commands follow (slider
drags are instant), then closes after **60 s idle** so the phone app can still connect.
You can change the timeout under the integration's *Configure* menu (`0` = stay connected
permanently; this uses one proxy connection slot).

## Install (HACS)

1. HACS → ⋮ → *Custom repositories* → add this repo's URL, category **Integration**.
2. Install *LEDDMX BLE pixel controller*, restart Home Assistant.
3. The chain is auto-discovered (*Settings → Devices & services*). Otherwise use
   *Add integration → LEDDMX*.

## Protocol

9-byte frames written without response to characteristic `0000ffe1-…` (service `0000ffe0-…`):

```
7B FF <cmd> <args… padded with FF> BF
```

| cmd | meaning | frame |
|---|---|---|
| `04` | power | `7B FF 04 01 FF FF FF FF BF` (on) / `…04 00…` (off) |
| `07` | static RGB | `7B FF 07 RR GG BB 00 FF BF` |
| `01` | brightness | `7B FF 01 <pct*32/100> <pct 0-100> 00 FF FF BF` |
| `03` | effect | `7B FF 03 <1-210, FF=auto> FF FF FF FF BF` |
| `02` | speed | `7B FF 02 <1-100> FF 00 FF FF BF` |

The app also has frames for pixel IC type, color order and pixel count (`cmd 05`), plus a
password frame (`2A … AF`). This integration deliberately never sends them.

## PC proof of concept

`poc/ledctl.py` drives the chain straight from a PC (Windows/Linux/macOS) with `bleak`:

```bash
python -m venv .venv && .venv/Scripts/pip install bleak bleak-retry-connector
.venv/Scripts/python poc/discover.py                      # find it + dump GATT
.venv/Scripts/python poc/ledctl.py on color:255,0,0 bright:40
.venv/Scripts/python poc/ledctl.py mode:81 speed:70       # effect 81, speed 70
```

## Tests

```bash
pip install pytest-homeassistant-custom-component
pytest
```

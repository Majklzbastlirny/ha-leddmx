"""Frame builders for LEDDMX-01 BLE pixel controllers (LED LAMP app family).

Reverse-engineered from LED LAMP 4.3.7 (com.home.net.NetConnectBle) and verified
against a LEDDMX-000079 (100x WS2812). Every frame is 9 bytes:
    7B FF <cmd> <args, padded with FF> BF
written to characteristic FFE1 (service FFE0) without response.
"""
from __future__ import annotations

SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

_HEAD = 0x7B
_TAIL = 0xBF


def _frame(*body: int) -> bytes:
    data = [int(b) & 0xFF for b in body]
    if len(data) > 7:
        raise ValueError("frame body too long")
    data += [0xFF] * (7 - len(data))
    return bytes([_HEAD, *data, _TAIL])


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))


def power(on: bool) -> bytes:
    """Turn output on/off (on resumes whatever the controller was showing)."""
    return _frame(0xFF, 0x04, 0x01 if on else 0x00)


def color(r: int, g: int, b: int) -> bytes:
    """Static color for the whole chain."""
    return _frame(0xFF, 0x07, _clamp(r, 0, 255), _clamp(g, 0, 255), _clamp(b, 0, 255), 0x00)


def brightness(percent: int) -> bytes:
    """Brightness 0-100 %. The app sends a 0-32 scaled value and the raw percentage."""
    pct = _clamp(percent, 0, 100)
    return _frame(0xFF, 0x01, pct * 32 // 100, pct, 0x00)


def effect(effect_id: int) -> bytes:
    """Built-in animation 1-210, or 255 for auto-cycle."""
    return _frame(0xFF, 0x03, _clamp(effect_id, 1, 255))


def speed(value: int) -> bytes:
    """Animation speed 1-100."""
    return _frame(0xFF, 0x02, _clamp(value, 1, 100), 0xFF, 0x00)

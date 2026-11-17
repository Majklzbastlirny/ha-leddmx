"""Protocol for "LEDDMX-xxxxxx" BLE pixel controllers (LED LAMP app, LEDDMX-01- family).

Reverse-engineered from LED LAMP 4.3.7 (com.home.net.NetConnectBle).
GATT: service 0000ffe0-..., characteristic 0000ffe1-... (write-without-response + notify).
Every frame is 9 bytes: 0x7B, 0xFF, <cmd>, <args...padded with 0xFF>, 0xBF.
"""
from __future__ import annotations

import datetime

SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
ADV_SERVICE_UUID = "0000ffb0-0000-1000-8000-00805f9b34fb"

HEAD, TAIL = 0x7B, 0xBF


def _frame(*body: int) -> bytes:
    """Build a 9-byte frame: 7B <7 bytes padded with FF> BF."""
    body = [b & 0xFF for b in body]
    if len(body) > 7:
        raise ValueError("frame body too long")
    body += [0xFF] * (7 - len(body))
    return bytes([HEAD, *body, TAIL])


# --- LEDDMX-01- framing (7B FF cmd ...) ---------------------------------------

def power(on: bool) -> bytes:
    # bledmxturnOn/Off default branch
    return _frame(0xFF, 0x04, 0x01 if on else 0x00)


def power_alt(on: bool) -> bytes:
    # turnOn/turnOff(str contains "LEDDMX") variant
    return _frame(0x04, 0x04, 0x01 if on else 0x00)


def color(r: int, g: int, b: int) -> bytes:
    # setDmxRgb default branch: 7B FF 07 R G B 00 FF BF
    return _frame(0xFF, 0x07, r, g, b, 0x00)


def brightness(pct: int) -> bytes:
    # setBrightness LEDDMX branch: 7B FF 01 (pct*32/100) pct 00 FF FF BF
    pct = max(0, min(100, int(pct)))
    return _frame(0xFF, 0x01, pct * 32 // 100, pct, 0x00)


def mode(n: int) -> bytes:
    # setRgbMode / setSPIModel: 7B FF 03 n FF FF FF FF BF
    return _frame(0xFF, 0x03, n)


def speed(n: int, flag: int = 0) -> bytes:
    # setSpeed LEDDMX-01-: 7B FF 02 n FF flag FF FF BF
    return _frame(0xFF, 0x02, n, 0xFF, flag)


def direction(n: int) -> bytes:
    return _frame(0xFF, 0x0D, n)


def pause(n: int) -> bytes:
    return _frame(0xFF, 0x06, n)


def handshake(now: datetime.datetime | None = None, password: bytes = b"\xa1\x23\x45\x67") -> bytes:
    """Password/time frame the app sends 300 ms after connecting (setPassword(2, ...))."""
    now = now or datetime.datetime.now()
    dow = now.isoweekday()  # Mon=1..Sun=7, matches app's {7,1,2,...}[Calendar.DAY_OF_WEEK-1]
    return bytes([0x2A, 0x02, *password, ((dow << 5) | now.hour) & 0xFF, now.minute, 0xAF])

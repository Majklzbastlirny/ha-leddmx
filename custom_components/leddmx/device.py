"""BLE connection handling for a LEDDMX controller.

Deliberately free of Home Assistant imports so it can be exercised from a plain
Python environment (see poc/test_device.py).

The controller is write-only (no state notifications), so this class only
writes frames. It keeps the GATT connection open while commands keep coming
and drops it after `idle_timeout` seconds, so a slider drag in HA doesn't pay
a reconnect per step and the phone app / remote can still get in afterwards.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)

from .protocol import CHAR_UUID

_LOGGER = logging.getLogger(__name__)

WRITE_GAP = 0.06  # seconds between frames; the app throttles to 30-50 ms
DEFAULT_IDLE_TIMEOUT = 60.0

_WRITE_ERRORS = (BleakError, asyncio.TimeoutError, EOFError, OSError)


class LedDmxDevice:
    """Write-only connection manager for one controller."""

    def __init__(
        self,
        ble_device: BLEDevice,
        name: str | None = None,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
    ) -> None:
        self._ble_device = ble_device
        self._name = name or ble_device.name or ble_device.address
        self._idle_timeout = idle_timeout
        self._client: BleakClientWithServiceCache | None = None
        self._char = None
        self._lock = asyncio.Lock()
        self._idle_handle: asyncio.TimerHandle | None = None
        self._idle_task: asyncio.Task | None = None
        self._last_write = 0.0
        self._listeners: list[Callable[[bool], None]] = []

    # -- public -----------------------------------------------------------------

    @property
    def address(self) -> str:
        return self._ble_device.address

    @property
    def name(self) -> str:
        return self._name

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        """Update the BLEDevice (HA may route through a different proxy/adapter)."""
        self._ble_device = ble_device

    def add_connection_listener(self, cb: Callable[[bool], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    async def send(self, *frames: bytes) -> None:
        """Write one or more frames, connecting (and retrying once) as needed."""
        if not frames:
            return
        async with self._lock:
            self._cancel_idle()
            try:
                await self._write_frames(frames)
            except _WRITE_ERRORS as err:
                _LOGGER.debug("%s: write failed (%s), reconnecting and retrying", self._name, err)
                await self._drop_client()
                await self._write_frames(frames)
            finally:
                self._schedule_idle()

    async def disconnect(self) -> None:
        async with self._lock:
            self._cancel_idle()
            await self._drop_client()

    # -- internals --------------------------------------------------------------

    async def _write_frames(self, frames: tuple[bytes, ...]) -> None:
        client = await self._ensure_connected()
        for frame in frames:
            wait = WRITE_GAP - (time.monotonic() - self._last_write)
            if wait > 0:
                await asyncio.sleep(wait)
            _LOGGER.debug("%s <= %s", self._name, frame.hex(" "))
            await client.write_gatt_char(self._char, frame, response=False)
            self._last_write = time.monotonic()

    async def _ensure_connected(self) -> BleakClientWithServiceCache:
        if self._client is not None and self._client.is_connected:
            return self._client
        _LOGGER.debug("%s: connecting to %s", self._name, self._ble_device.address)
        client = await establish_connection(
            BleakClientWithServiceCache,
            self._ble_device,
            self._name,
            disconnected_callback=self._on_disconnected,
            ble_device_callback=lambda: self._ble_device,
            max_attempts=3,
        )
        char = client.services.get_characteristic(CHAR_UUID)
        if char is None:
            await client.disconnect()
            raise BleakError(f"{self._name}: characteristic {CHAR_UUID} not found")
        self._client, self._char = client, char
        self._notify(True)
        return client

    def _on_disconnected(self, client) -> None:
        if client is self._client:
            _LOGGER.debug("%s: disconnected", self._name)
            self._client = None
            self._char = None
            self._notify(False)

    async def _drop_client(self) -> None:
        client, self._client, self._char = self._client, None, None
        if client is not None:
            try:
                await client.disconnect()
            except _WRITE_ERRORS as err:  # already gone
                _LOGGER.debug("%s: disconnect error ignored: %s", self._name, err)
            self._notify(False)

    def _schedule_idle(self) -> None:
        if self._idle_timeout <= 0:
            return
        loop = asyncio.get_running_loop()
        self._idle_handle = loop.call_later(self._idle_timeout, self._idle_fired)

    def _cancel_idle(self) -> None:
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None

    def _idle_fired(self) -> None:
        self._idle_handle = None
        self._idle_task = asyncio.get_running_loop().create_task(self._idle_disconnect())

    async def _idle_disconnect(self) -> None:
        async with self._lock:
            if self._idle_handle is None:  # no newer command re-armed the timer
                _LOGGER.debug("%s: idle, disconnecting", self._name)
                await self._drop_client()

    def _notify(self, connected: bool) -> None:
        for cb in list(self._listeners):
            try:
                cb(connected)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("connection listener failed")

"""
BLE client for IR Blaster: scan by name, connect, send_command by index or name,
schedule/heartbeat, auto-reconnect (bleak).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Awaitable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from blaster.config import BLEConfig

# IR Blaster GATT UUIDs (must match ESP32 ble_server.h)
IR_SERVICE_UUID = "e97a0001-c116-4a63-a60f-0e9b4d3648f3"
CHAR_SAVED_UUID = "e97a0002-c116-4a63-a60f-0e9b4d3648f3"
CHAR_SEND_UUID = "e97a0003-c116-4a63-a60f-0e9b4d3648f3"
CHAR_STATUS_UUID = "e97a0004-c116-4a63-a60f-0e9b4d3648f3"
CHAR_SCHEDULE_UUID = "e97a0005-c116-4a63-a60f-0e9b4d3648f3"

logger = logging.getLogger(__name__)


async def find_device(config: BLEConfig) -> BLEDevice | None:
    """Scan for the IR Blaster by name. Returns the first matching device or None."""
    logger.info("Scanning for BLE device %s...", config.device_name)
    devices = await BleakScanner.discover(timeout=10.0)
    for d in devices:
        if d.name and config.device_name.lower() in d.name.lower():
            logger.info("Found %s at %s", d.name, d.address)
            return d
    logger.warning("Device %s not found", config.device_name)
    return None


class IRBlasterBLE:
    """
    BLE client for the IR Blaster. Connect, send_command(index), and optional
    auto-reconnect when disconnected.
    """

    def __init__(self, config: BLEConfig) -> None:
        self._config = config
        self._client: BleakClient | None = None
        self._device: BLEDevice | None = None
        self._on_disconnect: Callable[[], Awaitable[None]] | None = None
        self._name_to_index: dict[str, int] | None = None  # cache; None = invalid

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def connect(self) -> bool:
        """Discover device and connect. Returns True if connected."""
        if self._client and self._client.is_connected:
            return True
        device = await find_device(self._config)
        if not device:
            return False
        self._device = device
        self._client = BleakClient(device, disconnected_callback=self._handle_disconnect)
        try:
            await self._client.connect()
            self._name_to_index = None  # refresh saved codes on next use
            logger.info("Connected to %s", device.name or device.address)
            return True
        except Exception as e:
            logger.exception("Connect failed: %s", e)
            self._client = None
            self._device = None
            return False

    def _handle_disconnect(self, _client: BleakClient) -> None:
        logger.warning("BLE disconnected")
        if self._on_disconnect:
            asyncio.create_task(self._on_disconnect())

    def set_disconnect_callback(self, cb: Callable[[], Awaitable[None]] | None) -> None:
        self._on_disconnect = cb

    async def disconnect(self) -> None:
        self._on_disconnect = None
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._client = None
        self._device = None
        self._name_to_index = None

    async def wait_until_ready(self, timeout_seconds: float = 30.0) -> None:
        """
        Block until the connection has sufficient encryption for GATT read/write.
        Polls a read of Saved Codes until it succeeds or the timeout is reached.
        """
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to IR Blaster")
        deadline = time.monotonic() + timeout_seconds
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            try:
                await self.get_saved_codes(retries=1)
                return
            except Exception:
                await asyncio.sleep(0.5)
        raise TimeoutError(
            f"BLE link not ready after {timeout_seconds}s (encryption may not have completed)"
        )

    async def get_saved_codes(self, retries: int = 3) -> list[dict[str, Any]]:
        """Read Saved Codes characteristic and return parsed JSON array. Retries on empty/invalid response."""
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to IR Blaster")
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                raw = await self._client.read_gatt_char(CHAR_SAVED_UUID)
                if not raw:
                    raise ValueError("Saved Codes read returned empty")
                text = raw.decode("utf-8", errors="replace").strip()
                if not text:
                    raise ValueError("Saved Codes read returned empty string")
                data = json.loads(text)
                if not isinstance(data, list):
                    raise ValueError(f"Saved Codes is not a list: {type(data)}")
                return data
            except (json.JSONDecodeError, ValueError) as e:
                last_error = e
                if attempt < retries - 1:
                    logger.debug("Saved Codes read attempt %s failed: %s; retrying...", attempt + 1, e)
                    await asyncio.sleep(1.0)
                continue
        self._name_to_index = None
        raise last_error or RuntimeError("Saved Codes read failed")

    async def send_command_by_name(self, name: str) -> str:
        """
        Resolve name to index (cached), then send that index. Case-insensitive name match.
        """
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to IR Blaster")
        if self._name_to_index is None:
            codes = await self.get_saved_codes()
            self._name_to_index = {}
            for entry in codes:
                if not isinstance(entry, dict):
                    continue
                # Full format: index/name; compact (BLE): i/n
                idx = entry.get("index") if "index" in entry else entry.get("i")
                n = entry.get("name") or entry.get("n") or ""
                if n and isinstance(idx, int):
                    self._name_to_index[n.lower()] = idx
        key = name.lower()
        if key not in self._name_to_index:
            raise ValueError(f"No saved code named {name!r}")
        return await self.send_command(self._name_to_index[key])

    async def schedule_disconnect_command(self, command_name: str, delay_seconds: int) -> None:
        """Arm the ESP32 to run the given command after delay_seconds unless heartbeat resets it."""
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to IR Blaster")
        payload = json.dumps({"delay_seconds": delay_seconds, "command": command_name})
        await self._client.write_gatt_char(CHAR_SCHEDULE_UUID, payload.encode("utf-8"))

    async def send_heartbeat(self) -> None:
        """Reset the ESP32 delayed-command timer."""
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to IR Blaster")
        payload = json.dumps({"heartbeat": True})
        await self._client.write_gatt_char(CHAR_SCHEDULE_UUID, payload.encode("utf-8"))

    async def send_command(self, index: int) -> str:
        """
        Write the saved-code index to the Send Command characteristic and wait for
        the Status notification. Returns the status string (e.g. "OK:Red" or "ERR:...").
        """
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected to IR Blaster")
        if index < 0 or index > 255:
            raise ValueError("index must be 0..255")
        payload = bytes([index])
        result: asyncio.Future[str] = asyncio.get_event_loop().create_future()

        def on_status(_handle: int, data: bytearray) -> None:
            if not result.done():
                try:
                    result.set_result(data.decode("utf-8", errors="replace"))
                except Exception:
                    result.set_result("ERR:decode")

        await self._client.start_notify(CHAR_STATUS_UUID, on_status)
        try:
            await self._client.write_gatt_char(CHAR_SEND_UUID, payload)
            return await asyncio.wait_for(result, timeout=5.0)
        finally:
            await self._client.stop_notify(CHAR_STATUS_UUID)

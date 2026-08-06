"""
AppController — owns BLE lifecycle, AV monitoring, and safe config restart.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any

from bleak import BleakError

from blaster.av_monitor import get_initial_state, stream_av_events
from blaster.ble_client import IRBlasterBLE
from blaster.config import Config, default_config_path, schedule_delay_seconds
from blaster.state_machine import AVStateMachine
from blaster.utils import execute_specs, sanitize_log_message

logger = logging.getLogger("blaster")

RECONNECT_INTERVAL_SECONDS = 5.0


class AppController:
    """Long-lived controller for BLE + AV state + status for the HTTP UI."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = Path(config_path) if config_path else default_config_path()
        self.config = Config.load(self.config_path)
        self.ble = IRBlasterBLE(self.config.ble)
        self.sm = AVStateMachine(self._idle_delay())
        self._lock = asyncio.Lock()
        self._reconnecting = False
        self._running = False
        self._error: str | None = None
        self.last_command: str | None = None
        self.last_status: str | None = None
        self.cam = False
        self.mic = False
        self._av_active = False
        self._reconnect_task: asyncio.Task[None] | None = None
        self._av_task: asyncio.Task[None] | None = None
        self._tick_task: asyncio.Task[None] | None = None

    def _idle_delay(self) -> float:
        idle = self.config.events.Idle
        if idle and idle[0].Delay is not None:
            return float(idle[0].Delay)
        return 120.0

    def _disconnect0(self):
        specs = self.config.events.OnDisconnect
        return specs[0] if specs else None

    def _on_command_sent(self, name: str, status: str) -> None:
        self.last_command = name
        self.last_status = status

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.ble.is_connected,
            "reconnecting": self._reconnecting,
            "state": self.sm.state.value,
            "cam": self.cam,
            "mic": self.mic,
            "last_command": self.last_command,
            "last_status": self.last_status,
            "device_name": self.config.ble.device_name,
            "error": self._error,
        }

    def config_dict(self) -> dict[str, Any]:
        return self.config.to_dict()

    async def start(self) -> None:
        """Connect if possible, then start AV/tick loops. Safe to call once."""
        if self._running:
            return
        self._running = True
        self.ble.set_disconnect_callback(self._on_disconnect)

        initial_cam, initial_mic = get_initial_state()
        self.cam = initial_cam
        self.mic = initial_mic
        self._av_active = initial_cam or initial_mic

        logger.info("Connecting to IR Blaster...")
        connected = await self.ble.connect()
        if not connected:
            self._error = (
                "Could not find or connect to IR Blaster. Ensure it is on and paired."
            )
            logger.error("%s", self._error)
            self._ensure_reconnect_task()
        else:
            self._error = None
            await self._run_after_connect()
            logger.info("Connected. Monitoring camera/mic...")
            cmd = self.sm.update(self._av_active)
            if cmd is not None:
                await execute_specs(
                    self.ble,
                    getattr(self.config.events, cmd),
                    "initial",
                    on_sent=self._on_command_sent,
                )

        self._av_task = asyncio.create_task(self._av_loop())
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        """Cancel tasks and disconnect cleanly."""
        self._running = False
        await self._cancel_reconnect()
        if self._av_task is not None:
            self._av_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._av_task
            self._av_task = None
        if self._tick_task is not None:
            self._tick_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tick_task
            self._tick_task = None
        self.ble.set_disconnect_callback(None)
        await self.ble.disconnect()
        await asyncio.sleep(0.5)
        logger.info("Shutdown complete.")

    async def request_reconnect(self) -> dict[str, Any]:
        """UI-triggered reconnect. No-op if already connected or in progress."""
        async with self._lock:
            if self.ble.is_connected:
                return {"ok": True, "message": "Already connected", **self.status()}
            if self._reconnecting:
                return {"ok": True, "message": "Reconnect already in progress", **self.status()}
            ok = await self._connect_and_arm_locked()
            return {
                "ok": ok,
                "message": "Connected" if ok else (self._error or "Connect failed"),
                **self.status(),
            }

    async def apply_config(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate, save config.yaml, and safely restart BLE with new settings."""
        new_config = Config.from_dict(data)
        async with self._lock:
            new_config.save(self.config_path)
            self.config = new_config
            await self._safe_restart_locked()
            return {"ok": True, "config": self.config.to_dict(), **self.status()}

    async def send_command(self, name: str) -> dict[str, Any]:
        """Send a named IR command immediately."""
        if not self.ble.is_connected:
            raise RuntimeError("Not connected to IR Blaster")
        status = await self.ble.send_command_by_name(name)
        self._on_command_sent(name, status)
        return {"ok": True, "name": name, "status": status, **self.status()}

    async def list_commands(self) -> list[str]:
        """Return saved-code names from the device, or empty if disconnected."""
        if not self.ble.is_connected:
            return []
        codes = await self.ble.get_saved_codes()
        names: list[str] = []
        for entry in codes:
            if not isinstance(entry, dict):
                continue
            n = entry.get("name") or entry.get("n") or ""
            if n:
                names.append(str(n))
        return names

    async def _safe_restart_locked(self) -> None:
        """Disconnect, rebuild BLE/SM from current config, reconnect and re-arm."""
        await self._cancel_reconnect()
        self.ble.set_disconnect_callback(None)
        await self.ble.disconnect()

        self.ble = IRBlasterBLE(self.config.ble)
        self.sm = AVStateMachine(self._idle_delay())
        self.ble.set_disconnect_callback(self._on_disconnect)

        await self._connect_and_arm_locked()

    async def _connect_and_arm_locked(self) -> bool:
        self._reconnecting = True
        try:
            logger.info("Connecting to IR Blaster...")
            if not await self.ble.connect():
                self._error = (
                    "Could not find or connect to IR Blaster. Ensure it is on and paired."
                )
                logger.error("%s", self._error)
                self._ensure_reconnect_task()
                return False
            self._error = None
            await self._run_after_connect()
            cmd = self.sm.update(self._av_active)
            if cmd is not None and self.ble.is_connected:
                await execute_specs(
                    self.ble,
                    getattr(self.config.events, cmd),
                    "after connect",
                    on_sent=self._on_command_sent,
                )
            return True
        finally:
            self._reconnecting = False

    async def _run_after_connect(self) -> None:
        try:
            await self.ble.wait_until_ready()
        except TimeoutError as e:
            logger.warning("%s", sanitize_log_message(e))
            return
        # Configure disconnect schedule before OnConnect commands.
        await self._restart_schedule()
        await execute_specs(
            self.ble,
            self.config.events.OnConnect,
            "on connect",
            on_sent=self._on_command_sent,
        )

    async def _restart_schedule(self) -> None:
        """Configure the device's disconnect-delayed command (countdown starts on disconnect)."""
        spec = self._disconnect0()
        if spec is not None:
            try:
                await self.ble.schedule_disconnect_command(
                    spec.NamedCommand,
                    schedule_delay_seconds(spec),
                )
            except (BleakError, asyncio.TimeoutError, RuntimeError) as e:
                logger.warning(
                    "Schedule disconnect command failed: %s", sanitize_log_message(e)
                )

    async def _on_disconnect(self) -> None:
        logger.warning("BLE disconnected")
        self._ensure_reconnect_task()

    def _ensure_reconnect_task(self) -> None:
        """Start the retry loop unless one is already running."""
        if not self._running:
            return
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._auto_reconnect())

    async def _auto_reconnect(self) -> None:
        while self._running:
            await asyncio.sleep(RECONNECT_INTERVAL_SECONDS)
            if self.ble.is_connected:
                return
            async with self._lock:
                if self.ble.is_connected:
                    return
                logger.info("Reconnecting to IR Blaster...")
                if await self._connect_and_arm_locked():
                    return

    async def _cancel_reconnect(self) -> None:
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None

    async def _av_loop(self) -> None:
        while True:
            try:
                async for cam, mic in stream_av_events():
                    self.cam = cam
                    self.mic = mic
                    self._av_active = cam or mic
                    cmd = self.sm.update(self._av_active)
                    if cmd is not None and self.ble.is_connected:
                        await execute_specs(
                            self.ble,
                            getattr(self.config.events, cmd),
                            on_sent=self._on_command_sent,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("AV stream error: %s", sanitize_log_message(e))

            logger.warning("AV stream ended unexpectedly. Restarting in 1 second...")
            await asyncio.sleep(1.0)

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            cmd = self.sm.update(self._av_active)
            if cmd is not None and self.ble.is_connected:
                await execute_specs(
                    self.ble,
                    getattr(self.config.events, cmd),
                    "cooldown",
                    on_sent=self._on_command_sent,
                )

"""
AppController — owns BLE lifecycle, AV monitoring, and safe config restart.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bleak import BleakError

from blaster.av_monitor import get_initial_state, stream_av_events
from blaster.ble_client import IRBlasterBLE
from blaster.config import Config, default_config_path, schedule_delay_seconds
from blaster.state_machine import AVStateMachine, CommandEvent
from blaster.utils import execute_specs, sanitize_log_message

logger = logging.getLogger("blaster")

RECONNECT_INTERVAL_SECONDS = 5.0
# Must stay below the ESP32 BLE_LINK_IDLE_TIMEOUT_MS (default 180s).
HEARTBEAT_INTERVAL_SECONDS = 60.0
EVENT_LOG_MAX = 100


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
        self._disconnect_timeout: dict[str, Any] = {
            "state": "unknown",
            "remaining_seconds": 0,
            "command": "",
        }
        self.last_command: str | None = None
        self.last_status: str | None = None
        self.cam = False
        self.mic = False
        self._av_active = False
        self._reconnect_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._av_task: asyncio.Task[None] | None = None
        self._tick_task: asyncio.Task[None] | None = None
        self._events: deque[dict[str, Any]] = deque(maxlen=EVENT_LOG_MAX)
        self._event_seq = 0

    def _idle_delay(self) -> float:
        idle = self.config.events.Idle
        if idle and idle[0].Delay is not None:
            return float(idle[0].Delay)
        return 120.0

    def _disconnect0(self):
        specs = self.config.events.OnDisconnect
        return specs[0] if specs else None

    def _connection_error(self) -> str:
        detail = getattr(self.ble, "last_connection_error", None)
        if isinstance(detail, str) and detail:
            return detail
        return "Could not find or connect to IR Blaster. Ensure it is on and in range."

    def _add_event(self, message: str, kind: str = "info") -> None:
        """Append a UI-facing activity event (ring buffer)."""
        self._event_seq += 1
        self._events.append(
            {
                "id": self._event_seq,
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "kind": kind,
                "message": sanitize_log_message(message),
            }
        )

    def _on_command_sent(self, name: str, status: str, context: str = "") -> None:
        self.last_command = name
        self.last_status = status
        ctx = f" ({context})" if context else ""
        self._add_event(f"Sent {name}{ctx} → {status}", "send")

    def _command_sent_cb(self, context: str = ""):
        return lambda name, status: self._on_command_sent(name, status, context)

    async def _dispatch(self, key: CommandEvent, context: str = "") -> None:
        """
        Run the Active/Idle command list for a state the machine just entered.

        Any wait inside the list is a window for the opposite state to arrive,
        so the send is abandoned if the machine has moved on: without that, an
        Idle command queued at the start of a break lands minutes later and
        overwrites the Active colour of a meeting that has already resumed.
        """
        if not self.ble.is_connected:
            return
        await execute_specs(
            self.ble,
            getattr(self.config.events, key),
            context,
            on_sent=self._command_sent_cb(context or key),
            # Idle[0].Delay is the cooldown, already served before we got here.
            skip_first_delay=(key == "Idle"),
            still_wanted=lambda: self.sm.desired_command == key,
        )

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
            "disconnect_timeout": self._disconnect_timeout,
            "error": self._error,
            "events": list(self._events),
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
        self._add_event("Connecting to IR Blaster…", "conn")
        connected = await self.ble.connect()
        if not connected:
            self._error = self._connection_error()
            logger.error("%s", self._error)
            self._add_event(self._error, "error")
            self._ensure_reconnect_task()
        else:
            self._error = None
            quiet_reconnect = await self._run_after_connect()
            logger.info("Connected. Monitoring camera/mic...")
            self._add_event("Connected. Monitoring camera/mic…", "conn")
            self.sm.update(self._av_active)
            if not quiet_reconnect and self._av_active:
                await self._dispatch("Active", "after connect")

        self._av_task = asyncio.create_task(self._av_loop())
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        """Cancel tasks and disconnect cleanly."""
        self._running = False
        await self._cancel_reconnect()
        await self._cancel_heartbeat()
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
        # Preserve the existing token when the payload omits ble.auth_token
        # (older UI clients / partial updates).
        ble_payload = data.get("ble") if isinstance(data.get("ble"), dict) else None
        if not ble_payload or "auth_token" not in ble_payload:
            new_config.ble.auth_token = self.config.ble.auth_token
        async with self._lock:
            new_config.save(self.config_path)
            self.config = new_config
            self._add_event(
                f"Config saved (device: {self.config.ble.device_name})", "config"
            )
            await self._safe_restart_locked()
            return {"ok": True, "config": self.config.to_dict(), **self.status()}

    async def send_command(self, name: str) -> dict[str, Any]:
        """Send a named IR command immediately."""
        if not self.ble.is_connected:
            raise RuntimeError("Not connected to IR Blaster")
        try:
            status = await self.ble.send_command_by_name(name)
        except Exception as e:
            self._add_event(f"Send {name} failed: {e}", "error")
            raise
        self._on_command_sent(name, status, "manual")
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
        await self._cancel_heartbeat()
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
            self._add_event("Connecting to IR Blaster…", "conn")
            if not await self.ble.connect():
                self._error = self._connection_error()
                logger.error("%s", self._error)
                self._add_event(self._error, "error")
                self._ensure_reconnect_task()
                return False
            self._error = None
            quiet_reconnect = await self._run_after_connect()
            if quiet_reconnect is None:
                self._error = "BLE link setup failed; reconnecting."
                await self.ble.reset_connection()
                self._ensure_reconnect_task()
                return False
            if self.ble.is_connected:
                self._add_event("Connected to IR Blaster", "conn")
            self.sm.update(self._av_active)
            if not quiet_reconnect and self._av_active:
                await self._dispatch("Active", "after connect")
            # Report the link state we actually ended with: the device can drop
            # us again while we are still arming it.
            return self.ble.is_connected
        finally:
            self._reconnecting = False

    async def _run_after_connect(self) -> bool | None:
        """Arm the link; return quiet-reconnect state, or None on setup failure."""
        try:
            await self.ble.wait_until_ready()
        except (BleakError, TimeoutError, RuntimeError) as e:
            logger.warning("%s", sanitize_log_message(e))
            self._add_event(f"BLE link not ready: {e}", "error")
            return None
        if not self.ble.is_connected:
            return None

        try:
            timeout_state = await self.ble.get_disconnect_timeout_state()
            self._disconnect_timeout = dict(timeout_state)
        except (BleakError, asyncio.TimeoutError, RuntimeError, TypeError, ValueError) as e:
            # Firmware without the snapshot leaves a plain status string in
            # Status. Preserve the established behavior when there is no
            # authoritative source of truth to consult.
            logger.warning(
                "Disconnect timeout state unavailable: %s", sanitize_log_message(e)
            )
            self._disconnect_timeout = {
                "state": "unknown",
                "remaining_seconds": 0,
                "command": "",
            }

        quiet_reconnect = self._disconnect_timeout["state"] == "interrupted"
        if not await self._restart_schedule():
            return None
        if quiet_reconnect:
            remaining = self._disconnect_timeout["remaining_seconds"]
            command = self._disconnect_timeout["command"] or "scheduled command"
            self._add_event(
                f"Reconnect canceled {command} timeout with {remaining}s remaining; "
                "light commands suppressed",
                "conn",
            )
        else:
            # Await the entire sequence, including all delays. The caller only
            # evaluates and sends Active after OnConnect has fully completed.
            await execute_specs(
                self.ble,
                self.config.events.OnConnect,
                "on connect",
                on_sent=self._command_sent_cb("on connect"),
            )
        await self._start_heartbeat()
        return quiet_reconnect

    async def _restart_schedule(self) -> bool:
        """Configure the device's disconnect-delayed command (countdown starts on disconnect)."""
        spec = self._disconnect0()
        if spec is None:
            return True
        try:
            await self.ble.schedule_disconnect_command(
                spec.NamedCommand,
                schedule_delay_seconds(spec),
            )
            return True
        except (BleakError, asyncio.TimeoutError, RuntimeError) as e:
            logger.warning(
                "Schedule disconnect command failed: %s", sanitize_log_message(e)
            )
            self._add_event(f"BLE schedule setup failed: {e}", "error")
            return False

    async def _start_heartbeat(self) -> None:
        """Keep the ESP32 GATT-idle watchdog fed while connected."""
        await self._cancel_heartbeat()
        if not self._running or not self.ble.is_connected:
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        while self._running and self.ble.is_connected:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            if not self._running or not self.ble.is_connected:
                return
            try:
                await self.ble.send_heartbeat()
            except (BleakError, asyncio.TimeoutError, RuntimeError) as e:
                logger.warning("Heartbeat failed: %s", sanitize_log_message(e))
                self._add_event(f"BLE heartbeat failed: {e}", "error")
                await self.ble.reset_connection()
                self._ensure_reconnect_task()
                return

    async def _cancel_heartbeat(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

    async def _on_disconnect(self) -> None:
        logger.warning("BLE disconnected")
        self._add_event("BLE disconnected", "conn")
        await self._cancel_heartbeat()
        self._ensure_reconnect_task()

    def _ensure_reconnect_task(self) -> None:
        """Start the retry loop unless one is already running."""
        if not self._running:
            return
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._auto_reconnect())

    def _supervise_connection(self) -> None:
        """
        Level-triggered safety net for the retry loop.

        Relying only on the disconnect callback to arm reconnection is not enough:
        the callback can fire while _auto_reconnect is still inside
        _connect_and_arm_locked, see a task that is not done yet, decline to start
        a new one, and then that task exits — leaving nothing scheduled. Re-checking
        the actual link state every tick means a dropped edge cannot strand the app.
        """
        if not self._running or self._reconnecting or self.ble.is_connected:
            return
        self._ensure_reconnect_task()

    async def _auto_reconnect(self) -> None:
        while self._running:
            await asyncio.sleep(RECONNECT_INTERVAL_SECONDS)
            if self.ble.is_connected:
                return
            async with self._lock:
                if self.ble.is_connected:
                    return
                logger.info("Reconnecting to IR Blaster...")
                self._add_event("Reconnecting to IR Blaster…", "conn")
                if await self._connect_and_arm_locked():
                    return

    async def _cancel_reconnect(self) -> None:
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
            self._reconnect_task = None

    def _note_av_change(self, cam: bool, mic: bool) -> None:
        if cam != self.cam:
            self._add_event(f"Camera {'on' if cam else 'off'}", "av")
        if mic != self.mic:
            self._add_event(f"Mic {'on' if mic else 'off'}", "av")

    async def _av_loop(self) -> None:
        while True:
            try:
                async for cam, mic in stream_av_events():
                    self._note_av_change(cam, mic)
                    self.cam = cam
                    self.mic = mic
                    self._av_active = cam or mic
                    cmd = self.sm.update(self._av_active)
                    if cmd is not None:
                        await self._dispatch(cmd)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("AV stream error: %s", sanitize_log_message(e))
                self._add_event(f"AV stream error: {e}", "error")

            logger.warning("AV stream ended unexpectedly. Restarting in 1 second...")
            await asyncio.sleep(1.0)

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            self._supervise_connection()
            cmd = self.sm.update(self._av_active)
            if cmd is not None:
                await self._dispatch(cmd, "cooldown")

"""
Blaster Mac Client — entry point. Run with: python -m blaster
"""
from __future__ import annotations

import asyncio
import logging
import sys

from blaster.av_monitor import get_initial_state, stream_av_events
from blaster.ble_client import IRBlasterBLE
from blaster.config import Config
from blaster.state_machine import AVStateMachine
from blaster.utils import execute_specs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("blaster")


async def run() -> None:
    config = Config.load()
    ble = IRBlasterBLE(config.ble)
    idle_delay = (
        config.events.Idle[0].Delay
        if config.events.Idle and config.events.Idle[0].Delay is not None
        else 120
    )
    sm = AVStateMachine(idle_delay)
    initial_cam, initial_mic = get_initial_state()
    last_av_active: bool = initial_cam or initial_mic

    hb0 = config.events.HeartbeatStopped[0] if config.events.HeartbeatStopped else None
    heartbeat_interval = (hb0.HeartbeatInterval if hb0 else None) or 60
    heartbeat_task: asyncio.Task[None] | None = None

    async def heartbeat_loop() -> None:
        while True:
            await asyncio.sleep(heartbeat_interval)
            if not ble.is_connected:
                return
            try:
                await ble.send_heartbeat()
            except Exception as e:
                logger.debug("Heartbeat failed: %s", e)

    async def run_after_connect() -> None:
        """Run OnConnect events, schedule disconnect command, and start heartbeat. Call after every connect (initial and reconnect)."""
        nonlocal heartbeat_task
        try:
            await ble.wait_until_ready()
        except TimeoutError as e:
            logger.warning("%s", e)
            return
        # On connect: run each command with its delay (in order).
        await execute_specs(ble, config.events.OnConnect, "on connect")
        if hb0 is not None:
            try:
                await ble.schedule_disconnect_command(
                    hb0.NamedCommand,
                    hb0.Delay or 900,
                )
            except Exception as e:
                logger.warning("Schedule disconnect command failed: %s", e)
        if heartbeat_interval > 0:
            heartbeat_task = asyncio.create_task(heartbeat_loop())

    async def try_reconnect() -> None:
        while True:
            await asyncio.sleep(5.0)
            if ble.is_connected:
                return
            logger.info("Reconnecting to IR Blaster...")
            if await ble.connect():
                await run_after_connect()
                return

    ble.set_disconnect_callback(try_reconnect)

    logger.info("Connecting to IR Blaster...")
    if not await ble.connect():
        logger.error("Could not find or connect to IR Blaster. Ensure it is on and paired.")
        sys.exit(1)

    await run_after_connect()

    logger.info("Connected. Monitoring camera/mic...")

    # Apply initial AV state (e.g. if cam/mic already on, send Active command)
    cmd = sm.update(last_av_active)
    if cmd is not None:
        await execute_specs(ble, getattr(config.events, cmd), "initial")

    async def av_loop() -> None:
        nonlocal last_av_active
        try:
            async for cam, mic in stream_av_events():
                last_av_active = cam or mic
                cmd = sm.update(last_av_active)
                if cmd is not None and ble.is_connected:
                    await execute_specs(ble, getattr(config.events, cmd))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("AV stream error: %s", e)

    async def tick_loop() -> None:
        while True:
            await asyncio.sleep(1.0)
            cmd = sm.update(last_av_active)
            if cmd is not None and ble.is_connected:
                await execute_specs(ble, getattr(config.events, cmd), "cooldown")

    av_task = asyncio.create_task(av_loop())
    tick_task = asyncio.create_task(tick_loop())
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        av_task.cancel()
        tick_task.cancel()
        try:
            await av_task
        except asyncio.CancelledError:
            pass
        try:
            await tick_task
        except asyncio.CancelledError:
            pass
        ble.set_disconnect_callback(None)
        await ble.disconnect()
        await asyncio.sleep(0.5)
        logger.info("Shutdown complete.")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Interrupted.")
        sys.exit(0)


if __name__ == "__main__":
    main()

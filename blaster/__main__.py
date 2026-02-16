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

    async def try_reconnect() -> None:
        while True:
            await asyncio.sleep(5.0)
            if ble.is_connected:
                return
            logger.info("Reconnecting to IR Blaster...")
            if await ble.connect():
                return

    ble.set_disconnect_callback(try_reconnect)

    logger.info("Connecting to IR Blaster...")
    if not await ble.connect():
        logger.error("Could not find or connect to IR Blaster. Ensure it is on and paired.")
        sys.exit(1)

    # Wait until the link has proper encryption (macOS may not be ready immediately after connect).
    try:
        await ble.wait_until_ready()
    except TimeoutError as e:
        logger.warning("%s", e)
    else:
        # On connect: run each command with its delay (in order).
        for spec in config.events.OnConnect:
            if spec.Delay and spec.Delay > 0:
                await asyncio.sleep(spec.Delay)
            try:
                status = await ble.send_command_by_name(spec.NamedCommand)
                logger.info("Sent %s (on connect) -> %s", spec.NamedCommand, status)
            except Exception as e:
                logger.warning("Send %s on connect failed: %s", spec.NamedCommand, e)

    hb0 = config.events.HeartbeatStopped[0] if config.events.HeartbeatStopped else None
    if hb0 is not None:
        try:
            await ble.schedule_disconnect_command(
                hb0.NamedCommand,
                hb0.Delay or 900,
            )
        except Exception as e:
            logger.warning("Schedule disconnect command failed: %s", e)

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

    if heartbeat_interval > 0:
        heartbeat_task = asyncio.create_task(heartbeat_loop())

    logger.info("Connected. Monitoring camera/mic...")

    # Apply initial AV state (e.g. if cam/mic already on, send Active command)
    cmd = sm.update(last_av_active)
    if cmd is not None:
        specs = getattr(config.events, cmd)
        for spec in specs:
            if spec.Delay and spec.Delay > 0:
                await asyncio.sleep(spec.Delay)
            try:
                status = await ble.send_command_by_name(spec.NamedCommand)
                logger.info("Sent %s (initial) -> %s", spec.NamedCommand, status)
            except Exception as e:
                logger.warning("Send %s (initial) failed: %s", spec.NamedCommand, e)

    async def av_loop() -> None:
        nonlocal last_av_active
        try:
            async for cam, mic in stream_av_events():
                last_av_active = cam or mic
                cmd = sm.update(last_av_active)
                if cmd is not None and ble.is_connected:
                    for spec in getattr(config.events, cmd):
                        if spec.Delay and spec.Delay > 0:
                            await asyncio.sleep(spec.Delay)
                        try:
                            status = await ble.send_command_by_name(spec.NamedCommand)
                            logger.info("Sent %s -> %s", spec.NamedCommand, status)
                        except Exception as e:
                            logger.warning("Send %s failed: %s", spec.NamedCommand, e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("AV stream error: %s", e)

    async def tick_loop() -> None:
        while True:
            await asyncio.sleep(1.0)
            cmd = sm.update(last_av_active)
            if cmd is not None and ble.is_connected:
                for spec in getattr(config.events, cmd):
                    if spec.Delay and spec.Delay > 0:
                        await asyncio.sleep(spec.Delay)
                    try:
                        status = await ble.send_command_by_name(spec.NamedCommand)
                        logger.info("Sent %s (cooldown) -> %s", spec.NamedCommand, status)
                    except Exception as e:
                        logger.warning("Send %s (cooldown) failed: %s", spec.NamedCommand, e)

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

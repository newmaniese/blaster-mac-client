from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from blaster.ble_client import IRBlasterBLE
    from blaster.config import EventSpec

logger = logging.getLogger("blaster.utils")


async def execute_specs(ble: IRBlasterBLE, specs: list[EventSpec], context: str = "") -> None:
    """
    Executes a list of event specifications.

    For each spec:
      - If spec.Delay > 0, waits for that duration.
      - Tries to send the command by name using the BLE client.
      - Logs the outcome with context.
    """
    for spec in specs:
        if spec.Delay and spec.Delay > 0:
            await asyncio.sleep(spec.Delay)

        ctx_str = f" ({context})" if context else ""

        try:
            status = await ble.send_command_by_name(spec.NamedCommand)
            logger.info("Sent %s%s -> %s", spec.NamedCommand, ctx_str, status)
        except Exception as e:
            logger.warning("Send %s%s failed: %s", spec.NamedCommand, ctx_str, e)

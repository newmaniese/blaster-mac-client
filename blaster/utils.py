from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from blaster.ble_client import IRBlasterBLE
    from blaster.config import EventSpec

logger = logging.getLogger("blaster.utils")


def sanitize_log_message(msg: Any) -> str:
    """Escapes control characters like newlines and carriage returns to prevent log injection."""
    return str(msg).replace("\n", "\\n").replace("\r", "\\r")


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
            logger.info(
                "Sent %s%s -> %s",
                sanitize_log_message(spec.NamedCommand),
                sanitize_log_message(ctx_str),
                sanitize_log_message(status),
            )
        except Exception as e:
            logger.warning(
                "Send %s%s failed: %s",
                sanitize_log_message(spec.NamedCommand),
                sanitize_log_message(ctx_str),
                sanitize_log_message(e),
            )

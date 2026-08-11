from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from blaster.ble_client import IRBlasterBLE
    from blaster.config import EventSpec

logger = logging.getLogger("blaster.utils")

# Optional callback: (command_name, status_string) after a successful send.
OnCommandSent = Callable[[str, str], None]
# Checked after each delay: return False to abandon the rest of the sequence.
StillWanted = Callable[[], bool]


def sanitize_log_message(msg: Any) -> str:
    """Escapes control characters like newlines and carriage returns to prevent log injection."""
    return str(msg).replace("\n", "\\n").replace("\r", "\\r")


async def execute_specs(
    ble: IRBlasterBLE,
    specs: list[EventSpec],
    context: str = "",
    on_sent: OnCommandSent | None = None,
    *,
    skip_first_delay: bool = False,
    still_wanted: StillWanted | None = None,
) -> None:
    """
    Executes a list of event specifications.

    For each spec:
      - If spec.Delay > 0, waits for that duration.
      - Tries to send the command by name using the BLE client.
      - Logs the outcome with context.
      - Calls on_sent(name, status) on success.

    skip_first_delay drops the leading wait for callers that already served it.
    still_wanted is re-checked after every delay; a False result abandons the
    remaining specs, so a sequence cannot outlive the condition that queued it.
    """
    for index, spec in enumerate(specs):
        delay = 0 if (index == 0 and skip_first_delay) else spec.Delay
        if delay and delay > 0:
            await asyncio.sleep(delay)

        ctx_str = f" ({context})" if context else ""

        if still_wanted is not None and not still_wanted():
            logger.info(
                "Skipped %s%s: superseded while waiting",
                sanitize_log_message(spec.NamedCommand),
                sanitize_log_message(ctx_str),
            )
            return

        try:
            status = await ble.send_command_by_name(spec.NamedCommand)
            logger.info(
                "Sent %s%s -> %s",
                sanitize_log_message(spec.NamedCommand),
                sanitize_log_message(ctx_str),
                sanitize_log_message(status),
            )
            if on_sent is not None:
                on_sent(spec.NamedCommand, status)
        except Exception as e:
            logger.warning(
                "Send %s%s failed: %s",
                sanitize_log_message(spec.NamedCommand),
                sanitize_log_message(ctx_str),
                sanitize_log_message(e),
            )

"""
Blaster Mac Client — entry point. Run with: python -m blaster
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from blaster.app import AppController
from blaster.logging_setup import configure_logging
from blaster.web import DEFAULT_HOST, DEFAULT_PORT, start_web

logger = logging.getLogger("blaster")


async def run(
    config_path: Path | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    controller = AppController(config_path)
    await controller.start()
    runner = await start_web(controller, host=host, port=port)
    try:
        await asyncio.Future()
    finally:
        await runner.cleanup()
        await controller.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Blaster Mac Client")
    parser.add_argument("--config", type=Path, help="Path to config.yaml")
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"HTTP UI bind address (default {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"HTTP UI port (default {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        metavar="LEVEL",
        help="DEBUG, INFO, WARNING, or ERROR (default: BLASTER_LOG_LEVEL or INFO)",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Directory for rotating blaster.log (default: ~/Library/Logs/blaster-mac-client)",
    )
    args = parser.parse_args()

    try:
        log_path = configure_logging(args.log_level, log_dir=args.log_dir)
    except ValueError as e:
        parser.error(str(e))

    logger.info("Logging to %s", log_path)

    try:
        asyncio.run(run(config_path=args.config, host=args.host, port=args.port))
    except KeyboardInterrupt:
        logger.info("Interrupted.")
        sys.exit(0)


if __name__ == "__main__":
    main()

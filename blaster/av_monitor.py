"""
Camera/microphone detection via macOS log stream (control center sensor-indicators).
Uses the same events that drive the menu bar indicator dots.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from typing import AsyncIterator

# Predicate for sensor-indicators (cam/mic/loc). Must match macOS log format.
LOG_PREDICATE = (
    "subsystem == 'com.apple.controlcenter' AND "
    "category == 'sensor-indicators' AND "
    "formatString BEGINSWITH 'Active '"
)
PREFIX = "Active activity attributions changed to ["


def parse_event_message(event_message: str) -> tuple[bool, bool]:
    """
    Parse a single eventMessage string from log stream.
    Returns (camera_active, mic_active).
    """
    if not event_message.startswith(PREFIX):
        return False, False
    suffix = event_message[len(PREFIX) :].rstrip("]").strip()
    if not suffix:
        return False, False
    camera = False
    mic = False
    # Items are like "cam:com.apple.FaceTime" or "mic:us.zoom.xos", comma-separated
    for part in re.split(r",\s*", suffix):
        part = part.strip().strip("'\"")
        if part.startswith("cam:"):
            camera = True
        elif part.startswith("mic:"):
            mic = True
    return camera, mic


def get_initial_state() -> tuple[bool, bool]:
    """
    Run `log show --last 60s` with the sensor-indicators predicate and return
    (camera_active, mic_active) from the most recent event. If no events, returns (False, False).
    """
    cmd = [
        "/usr/bin/log", "show", "--last", "60s",
        "--style", "ndjson",
        "--predicate", LOG_PREDICATE,
    ]
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, False
    if out.returncode != 0 or not out.stdout:
        return False, False
    lines = [ln.strip() for ln in out.stdout.strip().splitlines() if ln.strip()]
    for line in reversed(lines):
        try:
            obj = json.loads(line)
            msg = obj.get("eventMessage") or obj.get("message") or ""
            if msg.startswith(PREFIX):
                return parse_event_message(msg)
        except (json.JSONDecodeError, KeyError):
            continue
    return False, False


async def stream_av_events() -> AsyncIterator[tuple[bool, bool]]:
    """
    Run `log stream` with the sensor-indicators predicate; parse NDJSON and
    yield (camera_active, mic_active) only when the state changes.
    """
    cmd = [
        "/usr/bin/log", "stream",
        "--style", "ndjson",
        "--predicate", LOG_PREDICATE,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    last: tuple[bool, bool] | None = None
    try:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            line = line.decode("utf-8", errors="replace").strip()
            if not line or line.startswith("Filtering"):
                continue
            try:
                obj = json.loads(line)
                msg = obj.get("eventMessage") or obj.get("message") or ""
                if not msg.startswith(PREFIX):
                    continue
                state = parse_event_message(msg)
                if state != last:
                    last = state
                    yield state
            except (json.JSONDecodeError, KeyError):
                continue
    finally:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except (ProcessLookupError, asyncio.TimeoutError):
            proc.kill()


if __name__ == "__main__":
    # Quick test: print initial state then first few stream events
    print("Initial state (last 60s):", get_initial_state())
    print("Streaming (Ctrl+C to stop)...")

    async def _run():
        async for cam, mic in stream_av_events():
            print(f"  cam={cam} mic={mic}")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)

"""
Camera/microphone detection via macOS log stream (control center sensor-indicators).
Uses the same events that drive the menu bar indicator dots.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from typing import AsyncIterator

# Control Center reports the active sensors in two different shapes depending on
# the macOS release, and a single machine can switch between them when Control
# Center restarts, so both have to be understood.
#   legacy: Active activity attributions changed to ["cam:us.zoom.xos"]
#   sorted: Sorted active attributions from SystemStatus update: [[cam] Zoom (us.zoom.xos)]
LEGACY_PREFIX = "Active activity attributions changed to ["
SORTED_PREFIX = "Sorted active attributions from SystemStatus update: ["

# Predicate for sensor-indicators (cam/mic/loc). Must match macOS log format.
LOG_PREDICATE = (
    "subsystem == 'com.apple.controlcenter' AND "
    "category == 'sensor-indicators' AND "
    "(formatString BEGINSWITH 'Active activity attributions changed to' OR "
    "formatString BEGINSWITH 'Sorted active attributions')"
)
SPLIT_PATTERN = re.compile(r",\s*")
# The sorted form tags each entry, e.g. "[cam] Zoom (us.zoom.xos)". An [aud] tag
# is audio playback rather than the microphone, so only cam/mic count here.
SENSOR_TAG_PATTERN = re.compile(r"\[(cam|mic)\]")


def is_sensor_message(event_message: str) -> bool:
    """True when the message is one of the sensor-indicator attribution forms."""
    return event_message.startswith((LEGACY_PREFIX, SORTED_PREFIX))


def parse_event_message(event_message: str) -> tuple[bool, bool]:
    """
    Parse a single eventMessage string from log stream.
    Returns (camera_active, mic_active).
    """
    if event_message.startswith(SORTED_PREFIX):
        tags = set(SENSOR_TAG_PATTERN.findall(event_message[len(SORTED_PREFIX) :]))
        return "cam" in tags, "mic" in tags
    if not event_message.startswith(LEGACY_PREFIX):
        return False, False
    suffix = event_message[len(LEGACY_PREFIX) :].rstrip("]").strip()
    if not suffix:
        return False, False
    camera = False
    mic = False
    # Items are like "cam:com.apple.FaceTime" or "mic:us.zoom.xos", comma-separated
    for part in SPLIT_PATTERN.split(suffix):
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
    for line in reversed(out.stdout.strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            msg = obj.get("eventMessage") or obj.get("message") or ""
            if is_sensor_message(msg):
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
        if proc.stdout is None:
            raise RuntimeError("Failed to open stdout for av_monitor subprocess.")
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
                if not is_sensor_message(msg):
                    continue
                state = parse_event_message(msg)
                if state != last:
                    last = state
                    yield state
            except (json.JSONDecodeError, KeyError):
                continue
    finally:
        if proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except ProcessLookupError:
                pass
            except asyncio.TimeoutError:
                proc.kill()



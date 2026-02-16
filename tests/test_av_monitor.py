"""Unit tests for AV monitor — parse sample NDJSON, camera/mic state extraction."""
import json

import pytest

from blaster.av_monitor import parse_event_message, PREFIX


def test_parse_empty_list() -> None:
    msg = PREFIX + "]"
    assert parse_event_message(msg) == (False, False)


def test_parse_cam_only() -> None:
    msg = PREFIX + "cam:com.apple.FaceTime]"
    assert parse_event_message(msg) == (True, False)


def test_parse_mic_only() -> None:
    msg = PREFIX + "mic:us.zoom.xos]"
    assert parse_event_message(msg) == (False, True)


def test_parse_cam_and_mic() -> None:
    msg = PREFIX + "cam:com.apple.FaceTime, mic:us.zoom.xos]"
    assert parse_event_message(msg) == (True, True)


def test_parse_multiple_cam_mic() -> None:
    msg = PREFIX + "cam:com.apple.PhotoBooth, mic:Audacity, loc:System Services]"
    assert parse_event_message(msg) == (True, True)


def test_parse_loc_only() -> None:
    msg = PREFIX + "loc:System Services]"
    assert parse_event_message(msg) == (False, False)


def test_parse_no_prefix_returns_false() -> None:
    assert parse_event_message("Something else") == (False, False)
    assert parse_event_message("") == (False, False)


def test_parse_real_format() -> None:
    # Example from macOS log stream
    raw = 'Active activity attributions changed to [cam:com.apple.PhotoBooth, mic:com.apple.FaceTime]'
    assert parse_event_message(raw) == (True, True)

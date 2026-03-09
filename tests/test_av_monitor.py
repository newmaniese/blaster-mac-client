"""Unit tests for AV monitor — parse sample NDJSON, camera/mic state extraction."""
import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from blaster.av_monitor import parse_event_message, PREFIX, get_initial_state


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


def test_get_initial_state_file_not_found() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert get_initial_state() == (False, False)


def test_get_initial_state_timeout() -> None:
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="log", timeout=15)):
        assert get_initial_state() == (False, False)


def test_get_initial_state_nonzero_return() -> None:
    mock_run = MagicMock()
    mock_run.returncode = 1
    mock_run.stdout = ""
    with patch("subprocess.run", return_value=mock_run):
        assert get_initial_state() == (False, False)


def test_get_initial_state_empty_stdout() -> None:
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = ""
    with patch("subprocess.run", return_value=mock_run):
        assert get_initial_state() == (False, False)


def test_get_initial_state_parse_success() -> None:
    mock_run = MagicMock()
    mock_run.returncode = 0
    # Simulate a log line with JSON content
    log_line = json.dumps({
        "eventMessage": PREFIX + "cam:com.apple.FaceTime]"
    })
    mock_run.stdout = log_line
    with patch("subprocess.run", return_value=mock_run):
        assert get_initial_state() == (True, False)


def test_get_initial_state_invalid_json() -> None:
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = "Not valid JSON"
    with patch("subprocess.run", return_value=mock_run):
        assert get_initial_state() == (False, False)

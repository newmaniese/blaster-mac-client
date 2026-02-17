import subprocess
from unittest.mock import MagicMock, patch
import json
import pytest
from blaster.av_monitor import get_initial_state, LOG_PREDICATE

@patch("subprocess.run")
def test_get_initial_state_success(mock_run):
    # Mock subprocess.run output
    mock_result = MagicMock()
    mock_result.returncode = 0
    # Simulate valid log lines with JSON
    # Note: get_initial_state iterates in reverse, so the last line in output is the first one checked.
    # If stdout has line 1 then line 2, line 2 is the most recent.

    # Line 1: Camera active
    log_line_1 = json.dumps({"eventMessage": "Active activity attributions changed to [cam:com.apple.FaceTime]"})
    # Line 2: Mic active
    log_line_2 = json.dumps({"eventMessage": "Active activity attributions changed to [mic:us.zoom.xos]"})

    mock_result.stdout = f"{log_line_1}\n{log_line_2}"
    mock_run.return_value = mock_result

    # Expected: latest event (log_line_2) determines the state, so Mic only.
    # Wait, the code says:
    # for line in reversed(lines): ... return parse_event_message(msg)
    # So it returns the first valid event it finds from the end.
    # If line 2 is last, it checks line 2 first. Line 2 is mic only.

    assert get_initial_state() == (False, True)

    # Verify subprocess.run call arguments
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == [
        "/usr/bin/log", "show", "--last", "60s",
        "--style", "ndjson",
        "--predicate", LOG_PREDICATE,
    ]

@patch("subprocess.run")
def test_get_initial_state_failure(mock_run):
    # Mock subprocess.run to fail
    mock_run.side_effect = FileNotFoundError
    assert get_initial_state() == (False, False)

@patch("subprocess.run")
def test_get_initial_state_empty(mock_run):
    # Mock subprocess.run with no output
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_run.return_value = mock_result

    assert get_initial_state() == (False, False)

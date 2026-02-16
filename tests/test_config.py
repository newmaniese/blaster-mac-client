"""Unit tests for config loading, defaults, and validation."""
import tempfile
from pathlib import Path

import pytest

from blaster.config import Config, BLEConfig, DEFAULT_DEVICE_NAME


def test_from_dict_empty_uses_defaults() -> None:
    cfg = Config.from_dict({})
    assert cfg.ble.device_name == DEFAULT_DEVICE_NAME
    assert len(cfg.events.OnConnect) == 1
    assert cfg.events.OnConnect[0].NamedCommand == "On"
    assert cfg.events.OnConnect[0].Delay == 0
    assert len(cfg.events.HeartbeatStopped) == 1
    assert cfg.events.HeartbeatStopped[0].NamedCommand == "Off"
    assert cfg.events.HeartbeatStopped[0].Delay == 900
    assert cfg.events.HeartbeatStopped[0].HeartbeatInterval == 60
    assert len(cfg.events.Active) == 1
    assert cfg.events.Active[0].NamedCommand == "Red"
    assert len(cfg.events.Idle) == 1
    assert cfg.events.Idle[0].NamedCommand == "Green"
    assert cfg.events.Idle[0].Delay == 120


def test_from_dict_partial() -> None:
    cfg = Config.from_dict({
        "ble": {"device_name": "My Blaster"},
        "events": {
            "OnConnect": {"NamedCommand": "PowerOn"},
            "HeartbeatStopped": {"Delay": 600},
        },
    })
    assert cfg.ble.device_name == "My Blaster"
    assert len(cfg.events.OnConnect) == 1
    assert cfg.events.OnConnect[0].NamedCommand == "PowerOn"
    assert cfg.events.OnConnect[0].Delay == 0
    assert cfg.events.HeartbeatStopped[0].Delay == 600
    assert cfg.events.HeartbeatStopped[0].NamedCommand == "Off"
    assert cfg.events.Active[0].NamedCommand == "Red"
    assert cfg.events.Idle[0].Delay == 120


def test_from_dict_full() -> None:
    cfg = Config.from_dict({
        "ble": {"device_name": "IR Blaster"},
        "events": {
            "OnConnect": {"NamedCommand": "On", "Delay": 5},
            "HeartbeatStopped": {"NamedCommand": "Off", "Delay": 900, "HeartbeatInterval": 45},
            "Active": {"NamedCommand": "Red"},
            "Idle": {"NamedCommand": "Green", "Delay": 90},
        },
    })
    assert cfg.ble.device_name == "IR Blaster"
    assert len(cfg.events.OnConnect) == 1
    assert cfg.events.OnConnect[0].NamedCommand == "On"
    assert cfg.events.OnConnect[0].Delay == 5
    assert cfg.events.HeartbeatStopped[0].NamedCommand == "Off"
    assert cfg.events.HeartbeatStopped[0].Delay == 900
    assert cfg.events.HeartbeatStopped[0].HeartbeatInterval == 45
    assert cfg.events.Active[0].NamedCommand == "Red"
    assert cfg.events.Idle[0].NamedCommand == "Green"
    assert cfg.events.Idle[0].Delay == 90


def test_on_connect_multiple_commands() -> None:
    cfg = Config.from_dict({
        "events": {
            "OnConnect": [
                {"NamedCommand": "On", "Delay": 0},
                {"NamedCommand": "Green", "Delay": 2},
            ],
        },
    })
    assert len(cfg.events.OnConnect) == 2
    assert cfg.events.OnConnect[0].NamedCommand == "On"
    assert cfg.events.OnConnect[0].Delay == 0
    assert cfg.events.OnConnect[1].NamedCommand == "Green"
    assert cfg.events.OnConnect[1].Delay == 2


def test_all_events_as_lists() -> None:
    """All events accept list format; HeartbeatStopped first spec has HeartbeatInterval."""
    cfg = Config.from_dict({
        "events": {
            "HeartbeatStopped": [
                {"NamedCommand": "Off", "Delay": 900, "HeartbeatInterval": 30},
            ],
            "Active": [
                {"NamedCommand": "Red"},
                {"NamedCommand": "Dim", "Delay": 1},
            ],
            "Idle": [
                {"NamedCommand": "Green", "Delay": 10},
            ],
        },
    })
    assert len(cfg.events.HeartbeatStopped) == 1
    assert cfg.events.HeartbeatStopped[0].HeartbeatInterval == 30
    assert len(cfg.events.Active) == 2
    assert cfg.events.Active[0].NamedCommand == "Red"
    assert cfg.events.Active[1].NamedCommand == "Dim"
    assert cfg.events.Active[1].Delay == 1
    assert len(cfg.events.Idle) == 1
    assert cfg.events.Idle[0].NamedCommand == "Green"
    assert cfg.events.Idle[0].Delay == 10


def test_load_from_file() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
ble:
  device_name: FromFile
events:
  Idle:
    NamedCommand: "Standby"
    Delay: 60
""")
        path = f.name
    try:
        cfg = Config.load(path)
        assert cfg.ble.device_name == "FromFile"
        assert len(cfg.events.Idle) == 1
        assert cfg.events.Idle[0].NamedCommand == "Standby"
        assert cfg.events.Idle[0].Delay == 60
    finally:
        Path(path).unlink(missing_ok=True)


def test_load_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        Config.load("/nonexistent/config.yaml")

def test_negative_delay_validation() -> None:
    """Ensure that negative Delay raises ValueError."""
    data = {
        "events": {
            "OnConnect": {"NamedCommand": "On", "Delay": -5},
        }
    }
    with pytest.raises(ValueError, match="Delay must be a non-negative integer"):
        Config.from_dict(data)


def test_negative_heartbeat_interval_validation() -> None:
    """Ensure that negative HeartbeatInterval raises ValueError."""
    data = {
        "events": {
            "HeartbeatStopped": {"NamedCommand": "Off", "HeartbeatInterval": -60},
        }
    }
    with pytest.raises(ValueError, match="HeartbeatInterval must be a non-negative integer"):
        Config.from_dict(data)


def test_invalid_type_delay() -> None:
    """Ensure that non-integer Delay raises ValueError."""
    data = {
        "events": {
            "OnConnect": {"NamedCommand": "On", "Delay": "invalid"},
        }
    }
    with pytest.raises(ValueError, match="Delay must be a non-negative integer"):
        Config.from_dict(data)


def test_invalid_type_heartbeat_interval() -> None:
    """Ensure that non-integer HeartbeatInterval raises ValueError."""
    data = {
        "events": {
            "HeartbeatStopped": {"NamedCommand": "Off", "HeartbeatInterval": "invalid"},
        }
    }
    with pytest.raises(ValueError, match="HeartbeatInterval must be a non-negative integer"):
        Config.from_dict(data)

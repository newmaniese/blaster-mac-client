"""Unit tests for config loading, defaults, and validation."""
import tempfile
from pathlib import Path

import pytest

from blaster.config import (
    AUTH_TOKEN_ENV,
    AUTH_TOKEN_FILENAME,
    Config,
    DEFAULT_DEVICE_NAME,
    schedule_delay_seconds,
)


def test_from_dict_empty_uses_defaults() -> None:
    cfg = Config.from_dict({})
    assert cfg.ble.device_name == DEFAULT_DEVICE_NAME
    assert len(cfg.events.OnConnect) == 1
    assert cfg.events.OnConnect[0].NamedCommand == "On"
    assert cfg.events.OnConnect[0].Delay == 0
    assert len(cfg.events.OnDisconnect) == 1
    assert cfg.events.OnDisconnect[0].NamedCommand == "Off"
    assert cfg.events.OnDisconnect[0].Delay == 900
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
            "OnDisconnect": {"Delay": 600},
        },
    })
    assert cfg.ble.device_name == "My Blaster"
    assert len(cfg.events.OnConnect) == 1
    assert cfg.events.OnConnect[0].NamedCommand == "PowerOn"
    assert cfg.events.OnConnect[0].Delay == 0
    assert cfg.events.OnDisconnect[0].Delay == 600
    assert cfg.events.OnDisconnect[0].NamedCommand == "Off"
    assert cfg.events.Active[0].NamedCommand == "Red"
    assert cfg.events.Idle[0].Delay == 120


def test_from_dict_full() -> None:
    cfg = Config.from_dict({
        "ble": {"device_name": "IR Blaster"},
        "events": {
            "OnConnect": {"NamedCommand": "On", "Delay": 5},
            "OnDisconnect": {"NamedCommand": "Off", "Delay": 900},
            "Active": {"NamedCommand": "Red"},
            "Idle": {"NamedCommand": "Green", "Delay": 90},
        },
    })
    assert cfg.ble.device_name == "IR Blaster"
    assert len(cfg.events.OnConnect) == 1
    assert cfg.events.OnConnect[0].NamedCommand == "On"
    assert cfg.events.OnConnect[0].Delay == 5
    assert cfg.events.OnDisconnect[0].NamedCommand == "Off"
    assert cfg.events.OnDisconnect[0].Delay == 900
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
    """All events accept list format."""
    cfg = Config.from_dict({
        "events": {
            "OnDisconnect": [
                {"NamedCommand": "Off", "Delay": 900},
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
    assert len(cfg.events.OnDisconnect) == 1
    assert cfg.events.OnDisconnect[0].Delay == 900
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


def test_loads_auth_token_from_config_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "ble:\n  device_name: Test\n  auth_token: yaml-token-12345678\n"
    )

    cfg = Config.load(config_path)

    assert cfg.ble.auth_token == "yaml-token-12345678"
    assert cfg.to_dict()["ble"]["auth_token"] == "yaml-token-12345678"


def test_loads_private_ble_auth_token_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("ble: {device_name: Test}\n")
    (tmp_path / AUTH_TOKEN_FILENAME).write_text("file-token-123456789\n")

    cfg = Config.load(config_path)

    assert cfg.ble.auth_token == "file-token-123456789"


def test_config_auth_token_preferred_over_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "ble:\n  device_name: Test\n  auth_token: yaml-token-12345678\n"
    )
    (tmp_path / AUTH_TOKEN_FILENAME).write_text("file-token-123456789\n")

    cfg = Config.load(config_path)

    assert cfg.ble.auth_token == "yaml-token-12345678"


def test_auth_token_environment_takes_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "ble:\n  auth_token: yaml-token-12345678\n"
    )
    (tmp_path / AUTH_TOKEN_FILENAME).write_text("file-token-123456789\n")
    monkeypatch.setenv(AUTH_TOKEN_ENV, "environment-token-123456")

    cfg = Config.load(config_path)

    assert cfg.ble.auth_token == "environment-token-123456"


def test_rejects_short_auth_token_in_config() -> None:
    with pytest.raises(ValueError, match="16–64"):
        Config.from_dict({"ble": {"auth_token": "too-short"}})


def test_rejects_short_auth_token_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n")
    (tmp_path / AUTH_TOKEN_FILENAME).write_text("too-short\n")

    with pytest.raises(ValueError, match="16–64"):
        Config.load(config_path)


def test_negative_delay_validation() -> None:
    """Ensure that negative Delay raises ValueError."""
    data = {
        "events": {
            "OnConnect": {"NamedCommand": "On", "Delay": -5},
        }
    }
    with pytest.raises(ValueError, match="Delay must be a non-negative integer"):
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


def test_schedule_delay_zero_uses_default() -> None:
    """Delay 0 means unset, so the device is configured with the 900s default."""
    cfg = Config.from_dict({
        "events": {
            "OnDisconnect": {"NamedCommand": "Off", "Delay": 0},
        }
    })
    assert schedule_delay_seconds(cfg.events.OnDisconnect[0]) == 900


def test_default_config_path_ignores_cwd(tmp_path) -> None:
    """Ensure _default_config_path ignores config.yaml in CWD."""
    from blaster.config import _default_config_path
    import os

    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        (tmp_path / "config.yaml").write_text("ble: {device_name: Malicious}")

        path = _default_config_path()

        assert path != tmp_path / "config.yaml"
        assert path.name == "config.yaml"
        assert path.is_absolute()
    finally:
        os.chdir(original_cwd)


def test_string_only_event_spec() -> None:
    """Test events defined as strings in a list (not dicts)."""
    cfg = Config.from_dict({
        "events": {
            "Active": ["Red", "Blue"],
            "Idle": ["Green"],
            "OnDisconnect": ["MyOff"],
        },
    })
    assert len(cfg.events.Active) == 2
    assert cfg.events.Active[0].NamedCommand == "Red"
    assert cfg.events.Active[0].Delay == 0
    assert cfg.events.Active[1].NamedCommand == "Blue"
    assert cfg.events.Active[1].Delay == 0

    assert len(cfg.events.Idle) == 1
    assert cfg.events.Idle[0].NamedCommand == "Green"
    assert cfg.events.Idle[0].Delay == 0

    assert len(cfg.events.OnDisconnect) == 1
    assert cfg.events.OnDisconnect[0].NamedCommand == "MyOff"
    assert cfg.events.OnDisconnect[0].Delay == 0


def test_to_dict_round_trip() -> None:
    cfg = Config.from_dict({
        "ble": {"device_name": "RoundTrip"},
        "events": {
            "OnConnect": [
                {"NamedCommand": "On", "Delay": 0},
                {"NamedCommand": "Green", "Delay": 2},
            ],
            "OnDisconnect": [
                {"NamedCommand": "Off", "Delay": 45},
            ],
            "Active": [{"NamedCommand": "Red"}],
            "Idle": [{"NamedCommand": "Green", "Delay": 10}],
        },
    })
    again = Config.from_dict(cfg.to_dict())
    assert again.ble.device_name == "RoundTrip"
    assert again.events.OnConnect[1].NamedCommand == "Green"
    assert again.events.OnConnect[1].Delay == 2
    assert again.events.OnDisconnect[0].Delay == 45
    assert again.events.Idle[0].Delay == 10
    assert "HeartbeatInterval" not in cfg.to_dict()["events"]["OnDisconnect"][0]


def test_save_and_load_file(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    cfg = Config.from_dict({
        "ble": {
            "device_name": "Saved",
            "auth_token": "saved-token-123456",
        },
        "events": {
            "Idle": [{"NamedCommand": "Green", "Delay": 15}],
        },
    })
    cfg.save(path)
    loaded = Config.load(path)
    assert loaded.ble.device_name == "Saved"
    assert loaded.ble.auth_token == "saved-token-123456"
    assert loaded.events.Idle[0].Delay == 15
    assert loaded.events.Active[0].NamedCommand == "Red"

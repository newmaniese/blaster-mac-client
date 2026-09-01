"""
Load and validate config.yaml with defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_DEVICE_NAME = "IR Blaster"
AUTH_TOKEN_ENV = "BLASTER_AUTH_TOKEN"
AUTH_TOKEN_FILENAME = ".ble-auth-token"

# Event defaults (NamedCommand, Delay)
DEFAULT_ON_CONNECT = ("On", 0)
DEFAULT_ON_DISCONNECT = ("Off", 900)
DEFAULT_ACTIVE = ("Red", None)
DEFAULT_IDLE = ("Green", 120)

# An OnDisconnect Delay of 0 or None means "unset"; the device is configured with this.
DEFAULT_SCHEDULE_DELAY_SECONDS = 900


@dataclass
class BLEConfig:
    device_name: str
    auth_token: str = ""


@dataclass
class EventSpec:
    """One event: NamedCommand and optional Delay."""
    NamedCommand: str
    Delay: int | None = None


@dataclass
class EventsConfig:
    """All events are lists of { NamedCommand, Delay? }; multiple commands run in order with per-command delays."""
    OnConnect: list[EventSpec]
    OnDisconnect: list[EventSpec]  # first spec used for disconnect schedule
    Active: list[EventSpec]
    Idle: list[EventSpec]


@dataclass
class Config:
    ble: BLEConfig
    events: EventsConfig

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        if path is None:
            path = _default_config_path()
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        config = cls.from_dict(data)
        config.ble.auth_token = _resolve_auth_token(
            Path(path), config_token=config.ble.auth_token
        )
        return config

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        ble_data = data.get("ble") or {}
        events_data = data.get("events") or {}

        events = EventsConfig(
            OnConnect=_parse_event_specs(events_data, "OnConnect", DEFAULT_ON_CONNECT),
            OnDisconnect=_parse_event_specs(events_data, "OnDisconnect", DEFAULT_ON_DISCONNECT),
            Active=_parse_event_specs(events_data, "Active", DEFAULT_ACTIVE),
            Idle=_parse_event_specs(events_data, "Idle", DEFAULT_IDLE),
        )

        auth_token = str(ble_data.get("auth_token") or "").strip()
        _validate_auth_token(auth_token)

        return cls(
            ble=BLEConfig(
                device_name=ble_data.get("device_name") or DEFAULT_DEVICE_NAME,
                auth_token=auth_token,
            ),
            events=events,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for YAML / JSON round-trip."""
        return {
            "ble": {
                "device_name": self.ble.device_name,
                "auth_token": self.ble.auth_token,
            },
            "events": {
                "OnConnect": [_spec_to_dict(s) for s in self.events.OnConnect],
                "OnDisconnect": [_spec_to_dict(s) for s in self.events.OnDisconnect],
                "Active": [_spec_to_dict(s) for s in self.events.Active],
                "Idle": [_spec_to_dict(s) for s in self.events.Idle],
            },
        }

    def save(self, path: str | Path | None = None) -> None:
        """Validate via from_dict round-trip, then write config.yaml."""
        if path is None:
            path = _default_config_path()
        path = Path(path)
        # Re-parse to ensure the written file matches validated shape.
        validated = Config.from_dict(self.to_dict())
        with open(path, "w") as f:
            yaml.safe_dump(validated.to_dict(), f, default_flow_style=False, sort_keys=False)


def _parse_one_spec(
    raw_item: dict[str, Any] | str | None,
    default_cmd: str,
    default_delay: int | None,
) -> EventSpec:
    if raw_item is None:
        return EventSpec(
            NamedCommand=default_cmd,
            Delay=default_delay if default_delay is not None else 0,
        )
    if isinstance(raw_item, str):
        return EventSpec(NamedCommand=raw_item, Delay=0)
    cmd = raw_item.get("NamedCommand") or default_cmd

    if "Delay" in raw_item:
        delay = raw_item["Delay"]
        if delay is not None and (type(delay) is not int or delay < 0):
            raise ValueError(f"Delay must be a non-negative integer, got {delay!r}")
    else:
        delay = default_delay if default_delay is not None else 0

    return EventSpec(NamedCommand=cmd, Delay=delay)


def _parse_event_specs(
    events_data: dict[str, Any],
    key: str,
    default: tuple[str, int | None],
) -> list[EventSpec]:
    raw = events_data.get(key)
    default_cmd, default_delay = default[0], default[1]
    if raw is None:
        return [_parse_one_spec(None, default_cmd, default_delay)]
    if isinstance(raw, str):
        return [EventSpec(NamedCommand=raw, Delay=0)]
    if isinstance(raw, list):
        out: list[EventSpec] = []
        for i, item in enumerate(raw):
            out.append(_parse_one_spec(item, default_cmd, default_delay if i == 0 else 0))
        return out
    # single dict (backward compat)
    return [_parse_one_spec(raw, default_cmd, default_delay)]


def schedule_delay_seconds(spec: EventSpec) -> int:
    """Countdown the device starts on disconnect for an OnDisconnect spec."""
    return spec.Delay or DEFAULT_SCHEDULE_DELAY_SECONDS


def _spec_to_dict(spec: EventSpec) -> dict[str, Any]:
    out: dict[str, Any] = {"NamedCommand": spec.NamedCommand}
    if spec.Delay is not None:
        out["Delay"] = spec.Delay
    return out


def _validate_auth_token(token: str) -> None:
    if token and not 16 <= len(token) <= 64:
        raise ValueError("BLE auth token must be 16–64 characters")


def _resolve_auth_token(config_path: Path, config_token: str = "") -> str:
    """Resolve token: BLASTER_AUTH_TOKEN > config.yaml > .ble-auth-token."""
    token = os.environ.get(AUTH_TOKEN_ENV, "").strip()
    if not token:
        token = (config_token or "").strip()
    if not token:
        token_path = config_path.resolve().parent / AUTH_TOKEN_FILENAME
        if token_path.is_file():
            token = token_path.read_text(encoding="utf-8").strip()
    _validate_auth_token(token)
    return token


def default_config_path() -> Path:
    # Always resolve relative to the installed package, not the process CWD.
    return Path(__file__).resolve().parent.parent / "config.yaml"


def _default_config_path() -> Path:
    return default_config_path()

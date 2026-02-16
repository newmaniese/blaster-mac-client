"""
Load and validate config.yaml with defaults.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_DEVICE_NAME = "IR Blaster"

# Event defaults (NamedCommand, Delay, HeartbeatInterval)
DEFAULT_ON_CONNECT = ("On", 0, None)
DEFAULT_HEARTBEAT_STOPPED = ("Off", 900, 60)
DEFAULT_ACTIVE = ("Red", None, None)
DEFAULT_IDLE = ("Green", 120, None)


@dataclass
class BLEConfig:
    device_name: str


@dataclass
class EventSpec:
    """One event: NamedCommand and optional Delay / HeartbeatInterval."""
    NamedCommand: str
    Delay: int | None = None
    HeartbeatInterval: int | None = None


@dataclass
class EventsConfig:
    """All events are lists of { NamedCommand, Delay? }; multiple commands run in order with per-command delays."""
    OnConnect: list[EventSpec]
    HeartbeatStopped: list[EventSpec]  # first spec used for schedule + HeartbeatInterval
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
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        ble_data = data.get("ble") or {}
        events_data = data.get("events") or {}

        def one_spec(
            raw_item: dict[str, Any] | str | None,
            default_cmd: str,
            default_delay: int | None,
            default_hbi: int | None = None,
        ) -> EventSpec:
            if raw_item is None:
                return EventSpec(
                    NamedCommand=default_cmd,
                    Delay=default_delay if default_delay is not None else 0,
                    HeartbeatInterval=default_hbi,
                )
            if isinstance(raw_item, str):
                return EventSpec(NamedCommand=raw_item, Delay=0, HeartbeatInterval=default_hbi)
            cmd = raw_item.get("NamedCommand") or default_cmd

            if "Delay" in raw_item:
                delay = raw_item["Delay"]
                if delay is not None and (not isinstance(delay, int) or delay < 0):
                    raise ValueError(f"Delay must be a non-negative integer, got {delay!r}")
            else:
                delay = default_delay if default_delay is not None else 0

            if "HeartbeatInterval" in raw_item:
                hbi = raw_item["HeartbeatInterval"]
                if hbi is not None and (not isinstance(hbi, int) or hbi < 0):
                    raise ValueError(f"HeartbeatInterval must be a non-negative integer, got {hbi!r}")
            else:
                hbi = default_hbi

            return EventSpec(NamedCommand=cmd, Delay=delay, HeartbeatInterval=hbi)

        def event_specs(
            key: str,
            default: tuple[str, int | None, int | None],
            allow_heartbeat_interval: bool = False,
        ) -> list[EventSpec]:
            raw = events_data.get(key)
            default_cmd, default_delay, default_hbi = default[0], default[1], default[2]
            if raw is None:
                return [one_spec(None, default_cmd, default_delay, default_hbi if allow_heartbeat_interval else None)]
            if isinstance(raw, str):
                return [EventSpec(NamedCommand=raw, Delay=0, HeartbeatInterval=default_hbi if allow_heartbeat_interval else None)]
            if isinstance(raw, list):
                out: list[EventSpec] = []
                for i, item in enumerate(raw):
                    hbi = (default_hbi if allow_heartbeat_interval and i == 0 else None)
                    out.append(one_spec(item, default_cmd, default_delay if i == 0 else 0, hbi))
                return out
            # single dict (backward compat)
            return [one_spec(raw, default_cmd, default_delay, default_hbi if allow_heartbeat_interval else None)]

        return cls(
            ble=BLEConfig(
                device_name=ble_data.get("device_name") or DEFAULT_DEVICE_NAME,
            ),
            events=EventsConfig(
                OnConnect=event_specs("OnConnect", DEFAULT_ON_CONNECT),
                HeartbeatStopped=event_specs("HeartbeatStopped", DEFAULT_HEARTBEAT_STOPPED, allow_heartbeat_interval=True),
                Active=event_specs("Active", DEFAULT_ACTIVE),
                Idle=event_specs("Idle", DEFAULT_IDLE),
            ),
        )


def _default_config_path() -> Path:
    for candidate in (Path.cwd(), Path(__file__).resolve().parent.parent):
        p = candidate / "config.yaml"
        if p.is_file():
            return p
    return Path.cwd() / "config.yaml"

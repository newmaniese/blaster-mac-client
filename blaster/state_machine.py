"""
State machine: IDLE / ACTIVE / COOLDOWN. Cooldown after cam+mic off;
returns event key ("Active" or "Idle") when a command should be sent.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Literal


class State(Enum):
    IDLE = "idle"
    ACTIVE = "active"
    COOLDOWN = "cooldown"


# Event key returned when the caller should send the corresponding NamedCommand.
CommandEvent = Literal["Active", "Idle"]


class AVStateMachine:
    """
    Tracks camera/mic activity and cooldown. Call update(av_active, now) with
    the current aggregate activity and optional timestamp; returns the event key
    ("Active" or "Idle") for which to send the configured NamedCommand, or None.
    """

    def __init__(self, idle_delay_seconds: int | float) -> None:
        self.idle_delay_seconds = float(idle_delay_seconds)
        self._state = State.IDLE
        self._cooldown_start: float | None = None

    @property
    def state(self) -> State:
        return self._state

    def update(self, av_active: bool, now: float | None = None) -> CommandEvent | None:
        """
        Update with current camera/mic activity. Returns "Active" or "Idle" when
        the caller should send the corresponding NamedCommand, or None.
        """
        if now is None:
            now = time.monotonic()
        cmd: CommandEvent | None = None

        if av_active:
            if self._state == State.IDLE:
                self._state = State.ACTIVE
                cmd = "Active"
            elif self._state == State.COOLDOWN:
                self._state = State.ACTIVE
                self._cooldown_start = None
        else:
            if self._state == State.ACTIVE:
                self._state = State.COOLDOWN
                self._cooldown_start = now
            elif self._state == State.COOLDOWN and self._cooldown_start is not None:
                if (now - self._cooldown_start) >= self.idle_delay_seconds:
                    self._state = State.IDLE
                    self._cooldown_start = None
                    cmd = "Idle"

        return cmd

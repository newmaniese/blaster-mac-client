"""Unit tests for state machine — transitions, timer, event keys."""
import time

import pytest

from blaster.state_machine import AVStateMachine, State


@pytest.fixture
def sm() -> AVStateMachine:
    return AVStateMachine(idle_delay_seconds=2)


def test_initial_state_is_idle(sm: AVStateMachine) -> None:
    assert sm.state == State.IDLE


def test_idle_to_active_returns_active(sm: AVStateMachine) -> None:
    cmd = sm.update(True)
    assert cmd == "Active"
    assert sm.state == State.ACTIVE


def test_active_stays_active_while_av_on(sm: AVStateMachine) -> None:
    sm.update(True)
    cmd = sm.update(True)
    assert cmd is None
    assert sm.state == State.ACTIVE


def test_active_to_cooldown_on_av_off(sm: AVStateMachine) -> None:
    sm.update(True)
    cmd = sm.update(False)
    assert cmd is None
    assert sm.state == State.COOLDOWN


def test_cooldown_to_active_if_av_on_again(sm: AVStateMachine) -> None:
    sm.update(True)
    sm.update(False)
    cmd = sm.update(True)
    assert cmd is None
    assert sm.state == State.ACTIVE


def test_cooldown_to_idle_after_delay(sm: AVStateMachine) -> None:
    sm.update(True)
    sm.update(False)
    assert sm.state == State.COOLDOWN
    now = time.monotonic()
    cmd = sm.update(False, now=now)
    assert cmd is None
    cmd = sm.update(False, now=now + 1)
    assert cmd is None
    cmd = sm.update(False, now=now + 2)
    assert cmd == "Idle"
    assert sm.state == State.IDLE


def test_idle_stays_idle_when_av_off(sm: AVStateMachine) -> None:
    cmd = sm.update(False)
    assert cmd is None
    assert sm.state == State.IDLE
    cmd = sm.update(False)
    assert cmd is None

"""
Regression tests: a link that drops *while the app is arming it* must not strand
the retry loop.

Observed failure: connect() succeeded, the device dropped the link during
_run_after_connect, the disconnect callback found the still-running reconnect
task and declined to schedule another, then that task returned "success" and
exited. The app sat disconnected forever with reconnecting=False.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from blaster.config import Config


@pytest.fixture
def minimal_config(tmp_path: Path) -> Path:
    cfg = Config.from_dict({
        "events": {
            "OnConnect": {"NamedCommand": "On", "Delay": 0},
            "OnDisconnect": {"NamedCommand": "Off", "Delay": 900},
        },
    })
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg.to_dict()))
    return path


async def _never_yield():
    if False:  # pragma: no cover
        yield False, False


def _mock_ble(connected: list[bool]) -> MagicMock:
    ble = MagicMock()
    ble.wait_until_ready = AsyncMock()
    ble.schedule_disconnect_command = AsyncMock()
    ble.send_heartbeat = AsyncMock()
    ble.disconnect = AsyncMock()
    ble.reset_connection = AsyncMock()
    ble.send_command_by_name = AsyncMock(return_value="OK:test")
    ble.set_disconnect_callback = MagicMock()
    type(ble).is_connected = property(lambda self: connected[0])
    return ble


@pytest.mark.asyncio
async def test_drop_while_arming_reports_failure(minimal_config: Path) -> None:
    """connect() succeeding is not enough — a link lost while arming counts as failure."""
    from blaster.app import AppController

    connected = [False]

    async def connect() -> bool:
        connected[0] = True
        return True

    ble = _mock_ble(connected)
    ble.connect = AsyncMock(side_effect=connect)

    async def drop_during_arming() -> None:
        connected[0] = False

    ble.wait_until_ready = AsyncMock(side_effect=drop_during_arming)

    with (
        patch("blaster.app.IRBlasterBLE", return_value=ble),
        patch("blaster.app.execute_specs", new=AsyncMock()),
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_never_yield()),
    ):
        ctrl = AppController(minimal_config)
        ctrl._running = True
        try:
            assert await ctrl._connect_and_arm_locked() is False
        finally:
            ctrl._running = False
            await ctrl._cancel_reconnect()
            await ctrl._cancel_heartbeat()


@pytest.mark.asyncio
async def test_ready_timeout_drops_partial_connection(minimal_config: Path) -> None:
    """A transport link that never becomes GATT-ready must be retried."""
    from blaster.app import AppController

    connected = [True]
    ble = _mock_ble(connected)
    ble.connect = AsyncMock(return_value=True)
    ble.wait_until_ready = AsyncMock(side_effect=TimeoutError("not ready"))

    with (
        patch("blaster.app.IRBlasterBLE", return_value=ble),
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_never_yield()),
    ):
        ctrl = AppController(minimal_config)
        ctrl._running = True
        try:
            assert await ctrl._connect_and_arm_locked() is False
            ble.reset_connection.assert_awaited_once()
            assert ctrl._reconnect_task is not None
        finally:
            ctrl._running = False
            await ctrl._cancel_reconnect()


@pytest.mark.asyncio
async def test_schedule_failure_drops_partial_connection(minimal_config: Path) -> None:
    """Reconnect is incomplete until the disconnect safety schedule is armed."""
    from blaster.app import AppController

    connected = [True]
    ble = _mock_ble(connected)
    ble.connect = AsyncMock(return_value=True)
    ble.schedule_disconnect_command = AsyncMock(side_effect=RuntimeError("write failed"))

    with (
        patch("blaster.app.IRBlasterBLE", return_value=ble),
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_never_yield()),
    ):
        ctrl = AppController(minimal_config)
        ctrl._running = True
        try:
            assert await ctrl._connect_and_arm_locked() is False
            ble.reset_connection.assert_awaited_once()
        finally:
            ctrl._running = False
            await ctrl._cancel_reconnect()


@pytest.mark.asyncio
async def test_heartbeat_failure_forces_reconnect(minimal_config: Path) -> None:
    """A dead GATT link must not remain transport-connected indefinitely."""
    from blaster.app import AppController

    connected = [True]
    ble = _mock_ble(connected)
    ble.send_heartbeat = AsyncMock(side_effect=RuntimeError("write failed"))

    with (
        patch("blaster.app.IRBlasterBLE", return_value=ble),
        patch("blaster.app.HEARTBEAT_INTERVAL_SECONDS", 0),
    ):
        ctrl = AppController(minimal_config)
        ctrl._running = True
        try:
            await ctrl._heartbeat_loop()
            ble.reset_connection.assert_awaited_once()
            assert ctrl._reconnect_task is not None
        finally:
            ctrl._running = False
            await ctrl._cancel_reconnect()


@pytest.mark.asyncio
async def test_supervisor_rearms_after_task_exits(minimal_config: Path) -> None:
    """A finished retry task plus a dead link must be re-armed by the supervisor."""
    from blaster.app import AppController

    connected = [False]
    ble = _mock_ble(connected)
    ble.connect = AsyncMock(return_value=False)

    with (
        patch("blaster.app.IRBlasterBLE", return_value=ble),
        patch("blaster.app.execute_specs", new=AsyncMock()),
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_never_yield()),
    ):
        ctrl = AppController(minimal_config)
        ctrl._running = True

        # Simulate the stranded state: a reconnect task that already returned.
        done: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(0))
        await done
        ctrl._reconnect_task = done

        try:
            ctrl._supervise_connection()
            assert ctrl._reconnect_task is not done
            assert not ctrl._reconnect_task.done()
        finally:
            ctrl._running = False
            await ctrl._cancel_reconnect()
            await ctrl._cancel_heartbeat()


@pytest.mark.asyncio
async def test_supervisor_noop_while_connected(minimal_config: Path) -> None:
    """A healthy link must not spawn reconnect tasks every tick."""
    from blaster.app import AppController

    connected = [True]
    ble = _mock_ble(connected)
    ble.connect = AsyncMock(return_value=True)

    with (
        patch("blaster.app.IRBlasterBLE", return_value=ble),
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_never_yield()),
    ):
        ctrl = AppController(minimal_config)
        ctrl._running = True
        ctrl._supervise_connection()
        assert ctrl._reconnect_task is None
        ctrl._running = False


@pytest.mark.asyncio
async def test_stranding_scenario_end_to_end(minimal_config: Path) -> None:
    """
    Full reproduction: first connect drops during arming, and the app must still
    recover on a later attempt rather than going silent.
    """
    import blaster.app as app_module
    from blaster.app import AppController

    connected = [False]
    attempts: list[int] = []

    async def connect() -> bool:
        attempts.append(len(attempts))
        connected[0] = True
        return True

    ble = _mock_ble(connected)
    ble.connect = AsyncMock(side_effect=connect)

    async def maybe_drop() -> None:
        # Drop the link during arming for the first two attempts only.
        if len(attempts) < 3:
            connected[0] = False

    ble.wait_until_ready = AsyncMock(side_effect=maybe_drop)

    with (
        patch("blaster.app.IRBlasterBLE", return_value=ble),
        patch("blaster.app.execute_specs", new=AsyncMock()),
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_never_yield()),
        patch.object(app_module, "RECONNECT_INTERVAL_SECONDS", 0.01),
    ):
        ctrl = AppController(minimal_config)
        await ctrl.start()
        try:
            for _ in range(200):
                if ctrl.ble.is_connected:
                    break
                await asyncio.sleep(0.01)
            assert ctrl.ble.is_connected, "app never recovered from a drop while arming"
            assert len(attempts) >= 3
        finally:
            await ctrl.stop()

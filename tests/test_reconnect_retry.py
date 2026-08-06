"""Tests that a failed connect keeps retrying instead of giving up silently."""
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


def _mock_ble(connect: AsyncMock, connected: list[bool]) -> MagicMock:
    ble = MagicMock()
    ble.connect = connect
    ble.wait_until_ready = AsyncMock()
    ble.schedule_disconnect_command = AsyncMock()
    ble.disconnect = AsyncMock()
    ble.send_command_by_name = AsyncMock(return_value="OK:test")
    ble.set_disconnect_callback = MagicMock()
    type(ble).is_connected = property(lambda self: connected[0])
    return ble


@pytest.mark.asyncio
async def test_failed_initial_connect_schedules_retry(minimal_config: Path) -> None:
    """A device that is not found at startup must not leave the app idle forever."""
    from blaster.app import AppController

    connected = [False]
    ble = _mock_ble(AsyncMock(return_value=False), connected)

    with (
        patch("blaster.app.IRBlasterBLE", return_value=ble),
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_never_yield()),
    ):
        ctrl = AppController(minimal_config)
        await ctrl.start()
        try:
            assert ctrl._reconnect_task is not None
            assert not ctrl._reconnect_task.done()
        finally:
            await ctrl.stop()


@pytest.mark.asyncio
async def test_retry_loop_reconnects_after_failures(minimal_config: Path) -> None:
    """The retry loop keeps scanning until the device comes back."""
    import blaster.app as app_module
    from blaster.app import AppController

    connected = [False]
    attempts = []

    async def connect() -> bool:
        attempts.append(len(attempts))
        if len(attempts) < 3:
            return False
        connected[0] = True
        return True

    ble = _mock_ble(AsyncMock(side_effect=connect), connected)

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
            await asyncio.wait_for(ctrl._reconnect_task, timeout=2.0)
            assert ctrl.ble.is_connected
            assert len(attempts) == 3
            assert ctrl._error is None
        finally:
            await ctrl.stop()


@pytest.mark.asyncio
async def test_failed_config_restart_schedules_retry(minimal_config: Path) -> None:
    """Saving a device name that is not advertised must keep retrying."""
    from blaster.app import AppController

    connected = [True]

    async def connect() -> bool:
        return connected[0]

    ble = _mock_ble(AsyncMock(side_effect=connect), connected)

    with (
        patch("blaster.app.IRBlasterBLE", return_value=ble),
        patch("blaster.app.execute_specs", new=AsyncMock()),
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_never_yield()),
    ):
        ctrl = AppController(minimal_config)
        await ctrl.start()
        try:
            connected[0] = False
            result = await ctrl.apply_config(
                {"ble": {"device_name": "Nonexistent Device"}, "events": {}}
            )
            assert result["connected"] is False
            assert ctrl._reconnect_task is not None
            assert not ctrl._reconnect_task.done()
        finally:
            await ctrl.stop()

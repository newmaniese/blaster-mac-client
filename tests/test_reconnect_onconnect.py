"""Tests that OnConnect events run on initial connect and again after BLE reconnect."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from blaster.app import AppController
from blaster.config import Config


@pytest.fixture
def minimal_config(tmp_path: Path) -> tuple[Config, Path]:
    cfg = Config.from_dict({
        "events": {
            "OnConnect": {"NamedCommand": "On", "Delay": 0},
            "HeartbeatStopped": {"NamedCommand": "Off", "Delay": 900},
        },
    })
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg.to_dict()))
    return cfg, path


async def _never_yield():
    if False:  # pragma: no cover
        yield False, False


@pytest.mark.asyncio
async def test_onconnect_fires_on_initial_connect(minimal_config) -> None:
    """OnConnect events run once after initial BLE connect."""
    _cfg, path = minimal_config
    spec_calls: list[tuple] = []

    async def record_execute_specs(ble, specs, context="", on_sent=None):
        spec_calls.append((specs, context))

    mock_ble = MagicMock()
    mock_ble.connect = AsyncMock(return_value=True)
    mock_ble.wait_until_ready = AsyncMock()
    mock_ble.schedule_disconnect_command = AsyncMock()
    mock_ble.disconnect = AsyncMock()
    mock_ble.send_heartbeat = AsyncMock()
    mock_ble.send_command_by_name = AsyncMock(return_value="OK:test")
    mock_ble.set_disconnect_callback = MagicMock()
    mock_ble.is_connected = True

    with (
        patch("blaster.app.IRBlasterBLE", return_value=mock_ble),
        patch("blaster.app.execute_specs", side_effect=record_execute_specs),
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_never_yield()),
    ):
        ctrl = AppController(path)
        await ctrl.start()
        try:
            on_connect_calls = [
                c for c in spec_calls if c[0] == ctrl.config.events.OnConnect
            ]
            assert len(on_connect_calls) >= 1, (
                "OnConnect should run at least once on initial connect"
            )
            assert on_connect_calls[0][1] == "on connect"
        finally:
            await ctrl.stop()


@pytest.mark.asyncio
async def test_onconnect_fires_after_reconnect(minimal_config) -> None:
    """OnConnect events run again after a manual reconnect following disconnect."""
    _cfg, path = minimal_config
    spec_calls: list[tuple] = []

    async def record_execute_specs(ble, specs, context="", on_sent=None):
        spec_calls.append((specs, context))

    connected = [True]

    async def connect_and_mark():
        connected[0] = True
        return True

    mock_ble = MagicMock()
    mock_ble.connect = AsyncMock(side_effect=connect_and_mark)
    mock_ble.wait_until_ready = AsyncMock()
    mock_ble.schedule_disconnect_command = AsyncMock()
    mock_ble.disconnect = AsyncMock()
    mock_ble.send_heartbeat = AsyncMock()
    mock_ble.send_command_by_name = AsyncMock(return_value="OK:test")
    mock_ble.set_disconnect_callback = MagicMock()
    type(mock_ble).is_connected = property(lambda self: connected[0])

    with (
        patch("blaster.app.IRBlasterBLE", return_value=mock_ble),
        patch("blaster.app.execute_specs", side_effect=record_execute_specs),
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_never_yield()),
    ):
        ctrl = AppController(path)
        await ctrl.start()
        try:
            on_connect_initial = [
                c for c in spec_calls if c[0] == ctrl.config.events.OnConnect
            ]
            assert len(on_connect_initial) >= 1, "OnConnect should run on initial connect"

            connected[0] = False
            result = await ctrl.request_reconnect()
            assert result["ok"] is True
            assert result["connected"] is True

            on_connect_after = [
                c for c in spec_calls if c[0] == ctrl.config.events.OnConnect
            ]
            assert len(on_connect_after) >= 2, (
                "OnConnect should run again after reconnect (initial + reconnect)"
            )
            assert on_connect_after[1][1] == "on connect"
        finally:
            await ctrl.stop()

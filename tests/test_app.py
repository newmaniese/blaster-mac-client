"""Tests for AppController status, reconnect, and safe config restart."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from blaster.app import AppController
from blaster.config import Config


def _write_config(path: Path, data: dict | None = None) -> Path:
    payload = data or {
        "ble": {"device_name": "Test Blaster"},
        "events": {
            "OnConnect": [{"NamedCommand": "On", "Delay": 0}],
            "OnDisconnect": [
                {"NamedCommand": "Off", "Delay": 900}
            ],
            "Active": [{"NamedCommand": "Red"}],
            "Idle": [{"NamedCommand": "Green", "Delay": 120}],
        },
    }
    path.write_text(yaml.safe_dump(payload))
    return path


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return _write_config(tmp_path / "config.yaml")


def _mock_ble(connected: bool = True) -> MagicMock:
    ble = MagicMock()
    ble.is_connected = connected
    ble.connect = AsyncMock(return_value=connected)
    ble.disconnect = AsyncMock()
    ble.wait_until_ready = AsyncMock()
    ble.schedule_disconnect_command = AsyncMock()
    ble.send_heartbeat = AsyncMock()
    ble.send_command_by_name = AsyncMock(return_value="OK:Red")
    ble.get_saved_codes = AsyncMock(
        return_value=[{"name": "Red", "index": 0}, {"name": "Green", "index": 1}]
    )
    ble.set_disconnect_callback = MagicMock()
    return ble


async def _empty_av_stream():
    if False:  # pragma: no cover
        yield False, False


@pytest.mark.asyncio
async def test_status_snapshot(config_path: Path) -> None:
    with (
        patch("blaster.app.IRBlasterBLE") as ble_cls,
        patch("blaster.app.get_initial_state", return_value=(False, True)),
        patch("blaster.app.stream_av_events", return_value=_empty_av_stream()),
    ):
        ble = _mock_ble(True)
        ble_cls.return_value = ble
        ctrl = AppController(config_path)
        await ctrl.start()
        try:
            status = ctrl.status()
            assert status["connected"] is True
            assert status["cam"] is False
            assert status["mic"] is True
            assert status["device_name"] == "Test Blaster"
            assert status["state"] in ("idle", "active", "cooldown")
            assert status["reconnecting"] is False
        finally:
            await ctrl.stop()


@pytest.mark.asyncio
async def test_request_reconnect_when_connected(config_path: Path) -> None:
    with (
        patch("blaster.app.IRBlasterBLE") as ble_cls,
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_empty_av_stream()),
    ):
        ble = _mock_ble(True)
        ble_cls.return_value = ble
        ctrl = AppController(config_path)
        await ctrl.start()
        try:
            result = await ctrl.request_reconnect()
            assert result["ok"] is True
            assert "Already connected" in result["message"]
            assert ble.connect.await_count == 1  # only initial start
        finally:
            await ctrl.stop()


@pytest.mark.asyncio
async def test_request_reconnect_when_disconnected(config_path: Path) -> None:
    with (
        patch("blaster.app.IRBlasterBLE") as ble_cls,
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_empty_av_stream()),
        patch("blaster.app.execute_specs", new_callable=AsyncMock),
    ):
        ble = _mock_ble(False)
        ble._connected = False

        async def connect_impl():
            # First call (start): fail; later calls succeed
            if ble.connect.await_count == 1:
                ble._connected = False
                return False
            ble._connected = True
            return True

        ble.connect = AsyncMock(side_effect=connect_impl)
        type(ble).is_connected = property(lambda self: self._connected)
        ble_cls.return_value = ble

        ctrl = AppController(config_path)
        await ctrl.start()
        try:
            assert ctrl.status()["connected"] is False
            result = await ctrl.request_reconnect()
            assert result["ok"] is True
            assert result["connected"] is True
        finally:
            await ctrl.stop()


@pytest.mark.asyncio
async def test_apply_config_saves_and_restarts(config_path: Path) -> None:
    with (
        patch("blaster.app.IRBlasterBLE") as ble_cls,
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_empty_av_stream()),
        patch("blaster.app.execute_specs", new_callable=AsyncMock) as exec_specs,
    ):
        ble = _mock_ble(True)
        ble_cls.return_value = ble
        ctrl = AppController(config_path)
        await ctrl.start()
        try:
            new_data = {
                "ble": {"device_name": "Renamed"},
                "events": {
                    "OnConnect": [{"NamedCommand": "On", "Delay": 0}],
                    "OnDisconnect": [
                        {"NamedCommand": "Off", "Delay": 30}
                    ],
                    "Active": [{"NamedCommand": "Red"}],
                    "Idle": [{"NamedCommand": "Green", "Delay": 5}],
                },
            }
            result = await ctrl.apply_config(new_data)
            assert result["ok"] is True
            assert ctrl.config.ble.device_name == "Renamed"
            assert ctrl.config.events.Idle[0].Delay == 5
            loaded = Config.load(config_path)
            assert loaded.ble.device_name == "Renamed"
            # New BLE client constructed for restart
            assert ble_cls.call_count >= 2
            assert ble.disconnect.await_count >= 1
            assert exec_specs.await_count >= 1
        finally:
            await ctrl.stop()


@pytest.mark.asyncio
async def test_send_command_updates_last(config_path: Path) -> None:
    with (
        patch("blaster.app.IRBlasterBLE") as ble_cls,
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_empty_av_stream()),
        patch("blaster.app.execute_specs", new_callable=AsyncMock),
    ):
        ble = _mock_ble(True)
        ble.send_command_by_name = AsyncMock(return_value="OK:Green")
        ble_cls.return_value = ble
        ctrl = AppController(config_path)
        await ctrl.start()
        try:
            result = await ctrl.send_command("Green")
            assert result["ok"] is True
            assert ctrl.last_command == "Green"
            assert ctrl.last_status == "OK:Green"
        finally:
            await ctrl.stop()


@pytest.mark.asyncio
async def test_list_commands(config_path: Path) -> None:
    with (
        patch("blaster.app.IRBlasterBLE") as ble_cls,
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_empty_av_stream()),
        patch("blaster.app.execute_specs", new_callable=AsyncMock),
    ):
        ble = _mock_ble(True)
        ble_cls.return_value = ble
        ctrl = AppController(config_path)
        await ctrl.start()
        try:
            names = await ctrl.list_commands()
            assert names == ["Red", "Green"]
        finally:
            await ctrl.stop()

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
async def test_status_includes_events(config_path: Path) -> None:
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
            status = ctrl.status()
            assert isinstance(status["events"], list)
            assert status["events"], "expected connect events after start"
            ev = status["events"][-1]
            assert "id" in ev and "ts" in ev and "message" in ev and "kind" in ev
            assert isinstance(ev["id"], int)
        finally:
            await ctrl.stop()


@pytest.mark.asyncio
async def test_send_command_appends_event(config_path: Path) -> None:
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
            before = ctrl.status()["events"][-1]["id"]
            result = await ctrl.send_command("Green")
            events = result["events"]
            assert events[-1]["id"] > before
            assert "Green" in events[-1]["message"]
            assert events[-1]["kind"] == "send"
        finally:
            await ctrl.stop()


def _recording_execute_specs(calls: list[dict]):
    async def _run(ble, specs, context="", on_sent=None, **kwargs):
        calls.append({"specs": specs, "context": context, **kwargs})

    return _run


@pytest.mark.asyncio
async def test_idle_dispatch_does_not_wait_out_the_cooldown_twice(
    config_path: Path,
) -> None:
    """Idle[0].Delay is the cooldown, so it must not also delay the send."""
    calls: list[dict] = []
    with (
        patch("blaster.app.IRBlasterBLE") as ble_cls,
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_empty_av_stream()),
        patch("blaster.app.execute_specs", side_effect=_recording_execute_specs(calls)),
    ):
        ble_cls.return_value = _mock_ble(True)
        ctrl = AppController(config_path)
        await ctrl.start()
        try:
            calls.clear()
            await ctrl._dispatch("Idle", "cooldown")
            assert calls, "Idle dispatch should reach execute_specs"
            assert calls[-1]["skip_first_delay"] is True
            assert ctrl._idle_delay() == 120
        finally:
            await ctrl.stop()


@pytest.mark.asyncio
async def test_idle_dispatch_is_abandoned_when_av_resumes(config_path: Path) -> None:
    """A pending Idle send must be dropped once the meeting is active again."""
    calls: list[dict] = []
    with (
        patch("blaster.app.IRBlasterBLE") as ble_cls,
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_empty_av_stream()),
        patch("blaster.app.execute_specs", side_effect=_recording_execute_specs(calls)),
    ):
        ble_cls.return_value = _mock_ble(True)
        ctrl = AppController(config_path)
        await ctrl.start()
        try:
            calls.clear()
            await ctrl._dispatch("Idle", "cooldown")
            still_wanted = calls[-1]["still_wanted"]
            assert still_wanted() is True
            ctrl.sm.update(True)
            assert still_wanted() is False
        finally:
            await ctrl.stop()


def _config_with_green_on_connect(path: Path) -> Path:
    return _write_config(
        path,
        {
            "ble": {"device_name": "Test Blaster"},
            "events": {
                "OnConnect": [
                    {"NamedCommand": "On", "Delay": 0},
                    {"NamedCommand": "Green", "Delay": 0},
                ],
                "OnDisconnect": [{"NamedCommand": "Off", "Delay": 900}],
                "Active": [{"NamedCommand": "Red", "Delay": 0}],
                "Idle": [{"NamedCommand": "Green", "Delay": 120}],
            },
        },
    )


def _ble_tracking_sends(sent: list[str], connected: list[bool]) -> MagicMock:
    ble = _mock_ble(True)

    async def record(name):
        sent.append(name)
        return f"OK:{name}"

    async def connect():
        connected[0] = True
        return True

    ble.send_command_by_name = AsyncMock(side_effect=record)
    ble.connect = AsyncMock(side_effect=connect)
    type(ble).is_connected = property(lambda self: connected[0])
    return ble


@pytest.mark.asyncio
async def test_reconnect_mid_meeting_restores_active_colour(tmp_path: Path) -> None:
    """A BLE drop while cam/mic are on must not leave the OnConnect colour showing."""
    path = _config_with_green_on_connect(tmp_path / "config.yaml")
    sent: list[str] = []
    connected = [True]
    ble = _ble_tracking_sends(sent, connected)

    with (
        patch("blaster.app.IRBlasterBLE", return_value=ble),
        patch("blaster.app.get_initial_state", return_value=(True, True)),
        patch("blaster.app.stream_av_events", return_value=_empty_av_stream()),
    ):
        ctrl = AppController(path)
        await ctrl.start()
        try:
            assert ctrl.sm.state.value == "active"
            assert sent[-1] == "Red", f"expected Red after initial connect, got {sent}"

            sent.clear()
            connected[0] = False
            await ctrl.request_reconnect()

            assert "Green" in sent, "OnConnect should still replay as configured"
            assert sent[-1] == "Red", (
                f"lights must end on the active colour, got {sent}"
            )
        finally:
            await ctrl.stop()


@pytest.mark.asyncio
async def test_connect_while_idle_does_not_resend_the_idle_colour(
    tmp_path: Path,
) -> None:
    """OnConnect already leaves Green showing, so no duplicate send is needed."""
    path = _config_with_green_on_connect(tmp_path / "config.yaml")
    sent: list[str] = []
    connected = [True]
    ble = _ble_tracking_sends(sent, connected)

    with (
        patch("blaster.app.IRBlasterBLE", return_value=ble),
        patch("blaster.app.get_initial_state", return_value=(False, False)),
        patch("blaster.app.stream_av_events", return_value=_empty_av_stream()),
    ):
        ctrl = AppController(path)
        await ctrl.start()
        try:
            assert sent == ["On", "Green"]
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

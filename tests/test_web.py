"""Tests for localhost HTTP API handlers."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import yaml
from aiohttp.test_utils import TestClient, TestServer

from blaster.app import AppController
from blaster.config import Config
from blaster.web import create_app


def _write_config(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "ble": {"device_name": "API Blaster"},
                "events": {
                    "OnConnect": [{"NamedCommand": "On", "Delay": 0}],
                    "OnDisconnect": [
                        {"NamedCommand": "Off", "Delay": 900}
                    ],
                    "Active": [{"NamedCommand": "Red"}],
                    "Idle": [{"NamedCommand": "Green", "Delay": 120}],
                },
            }
        )
    )
    return path


async def _empty_av_stream():
    if False:  # pragma: no cover
        yield False, False


@pytest_asyncio.fixture
async def client(tmp_path: Path):
    config_path = _write_config(tmp_path / "config.yaml")
    with (
        patch("blaster.app.IRBlasterBLE") as ble_cls,
        patch("blaster.app.get_initial_state", return_value=(True, False)),
        patch("blaster.app.stream_av_events", return_value=_empty_av_stream()),
        patch("blaster.app.execute_specs", new_callable=AsyncMock),
    ):
        ble = MagicMock()
        ble.is_connected = True
        ble.connect = AsyncMock(return_value=True)
        ble.disconnect = AsyncMock()
        ble.wait_until_ready = AsyncMock()
        ble.schedule_disconnect_command = AsyncMock()
        ble.send_heartbeat = AsyncMock()
        ble.send_command_by_name = AsyncMock(return_value="OK:Red")
        ble.get_saved_codes = AsyncMock(
            return_value=[{"n": "Red", "i": 0}, {"n": "Green", "i": 1}]
        )
        ble.set_disconnect_callback = MagicMock()
        ble_cls.return_value = ble

        ctrl = AppController(config_path)
        await ctrl.start()
        app = create_app(ctrl)
        server = TestServer(app)
        http = TestClient(server)
        await http.start_server()
        try:
            yield http, ctrl, ble
        finally:
            await http.close()
            await ctrl.stop()


@pytest.mark.asyncio
async def test_get_status(client) -> None:
    http, _ctrl, _ble = client
    resp = await http.get("/api/status")
    assert resp.status == 200
    data = await resp.json()
    assert data["connected"] is True
    assert data["cam"] is True
    assert data["mic"] is False
    assert data["disconnect_timeout"]["state"] == "unknown"
    assert data["device_name"] == "API Blaster"
    assert isinstance(data["events"], list)
    assert data["events"]
    assert {"id", "ts", "kind", "message"} <= set(data["events"][-1])


@pytest.mark.asyncio
async def test_get_config(client) -> None:
    http, _ctrl, _ble = client
    resp = await http.get("/api/config")
    assert resp.status == 200
    data = await resp.json()
    assert data["ble"]["device_name"] == "API Blaster"
    assert data["events"]["Active"][0]["NamedCommand"] == "Red"


@pytest.mark.asyncio
async def test_post_command(client) -> None:
    http, ctrl, ble = client
    resp = await http.post("/api/command", json={"name": "Red"})
    assert resp.status == 200
    data = await resp.json()
    assert data["ok"] is True
    assert data["last_command"] == "Red"
    ble.send_command_by_name.assert_awaited_with("Red")
    assert ctrl.last_command == "Red"


@pytest.mark.asyncio
async def test_post_command_missing_name(client) -> None:
    http, _ctrl, _ble = client
    resp = await http.post("/api/command", json={})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_post_reconnect(client) -> None:
    http, _ctrl, _ble = client
    resp = await http.post("/api/reconnect", json={})
    assert resp.status == 200
    data = await resp.json()
    assert data["ok"] is True
    assert "Already connected" in data["message"]


@pytest.mark.asyncio
async def test_get_commands(client) -> None:
    http, _ctrl, _ble = client
    resp = await http.get("/api/commands")
    assert resp.status == 200
    data = await resp.json()
    assert data["commands"] == ["Red", "Green"]


@pytest.mark.asyncio
async def test_put_config(client) -> None:
    http, ctrl, _ble = client
    payload = ctrl.config_dict()
    payload["ble"]["device_name"] = "Updated"
    payload["events"]["Idle"][0]["Delay"] = 7
    resp = await http.put("/api/config", json=payload)
    assert resp.status == 200
    data = await resp.json()
    assert data["ok"] is True
    assert data["config"]["ble"]["device_name"] == "Updated"
    assert ctrl.config.ble.device_name == "Updated"
    assert Config.load(ctrl.config_path).events.Idle[0].Delay == 7


@pytest.mark.asyncio
async def test_index_page(client) -> None:
    http, _ctrl, _ble = client
    resp = await http.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "Blaster" in text
    assert "Activity" in text
    assert 'id="activity-log"' in text
    assert 'id="disconnect-timeout"' in text

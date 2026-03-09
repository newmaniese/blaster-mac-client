"""Tests that OnConnect events run on initial connect and again after BLE reconnect."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blaster.config import Config


@pytest.fixture
def minimal_config() -> Config:
    return Config.from_dict({
        "events": {
            "OnConnect": {"NamedCommand": "On", "Delay": 0},
            "HeartbeatStopped": {"NamedCommand": "Off", "Delay": 900},
        },
    })


@pytest.mark.asyncio
async def test_onconnect_fires_on_initial_connect(minimal_config: Config) -> None:
    """OnConnect events run once after initial BLE connect."""
    spec_calls: list[tuple] = []

    async def record_execute_specs(ble, specs, context=""):
        spec_calls.append((specs, context))

    async def never_yield():
        while True:
            await asyncio.sleep(3600)
            yield (False, False)

    mock_ble = MagicMock()
    mock_ble.connect = AsyncMock(return_value=True)
    mock_ble.wait_until_ready = AsyncMock()
    mock_ble.schedule_disconnect_command = AsyncMock()
    mock_ble.disconnect = AsyncMock()
    mock_ble.set_disconnect_callback = MagicMock()
    mock_ble.is_connected = True

    with (
        patch("blaster.__main__.Config") as mock_config_class,
        patch("blaster.__main__.IRBlasterBLE") as mock_ble_class,
        patch("blaster.__main__.execute_specs", side_effect=record_execute_specs),
        patch("blaster.__main__.get_initial_state", return_value=(False, False)),
        patch("blaster.__main__.stream_av_events", return_value=never_yield()),
    ):
        mock_config_class.load.return_value = minimal_config
        mock_ble_class.return_value = mock_ble

        from blaster.__main__ import run

        task = asyncio.create_task(run())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    on_connect_calls = [c for c in spec_calls if c[0] == minimal_config.events.OnConnect]
    assert len(on_connect_calls) >= 1, "OnConnect should run at least once on initial connect"
    assert on_connect_calls[0][1] == "on connect"


@pytest.mark.asyncio
async def test_onconnect_fires_after_reconnect(minimal_config: Config) -> None:
    """OnConnect events run again after BLE disconnect and reconnect."""
    spec_calls: list[tuple] = []

    async def record_execute_specs(ble, specs, context=""):
        spec_calls.append((specs, context))

    connected = [True]

    async def never_yield():
        while True:
            await asyncio.sleep(3600)
            yield (False, False)

    mock_ble = MagicMock()
    mock_ble.connect = AsyncMock(return_value=True)
    mock_ble.wait_until_ready = AsyncMock()
    mock_ble.schedule_disconnect_command = AsyncMock()
    mock_ble.disconnect = AsyncMock()
    mock_ble.set_disconnect_callback = MagicMock()
    type(mock_ble).is_connected = property(lambda self: connected[0])

    with (
        patch("blaster.__main__.Config") as mock_config_class,
        patch("blaster.__main__.IRBlasterBLE") as mock_ble_class,
        patch("blaster.__main__.execute_specs", side_effect=record_execute_specs),
        patch("blaster.__main__.get_initial_state", return_value=(False, False)),
        patch("blaster.__main__.stream_av_events", return_value=never_yield()),
    ):
        mock_config_class.load.return_value = minimal_config
        mock_ble_class.return_value = mock_ble

        from blaster.__main__ import run

        task = asyncio.create_task(run())
        await asyncio.sleep(0.2)

        on_connect_initial = [c for c in spec_calls if c[0] == minimal_config.events.OnConnect]
        assert len(on_connect_initial) >= 1, "OnConnect should run on initial connect"

        disconnect_cb = mock_ble.set_disconnect_callback.call_args[0][0]
        connected[0] = False

        async def fast_sleep(_secs):
            pass  # Skip the 5s delay in try_reconnect without recursing into patched sleep

        with patch("blaster.__main__.asyncio.sleep", side_effect=fast_sleep):
            await disconnect_cb()

        on_connect_after = [c for c in spec_calls if c[0] == minimal_config.events.OnConnect]
        assert len(on_connect_after) >= 2, (
            "OnConnect should run again after reconnect (initial + reconnect)"
        )
        assert on_connect_after[1][1] == "on connect"

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

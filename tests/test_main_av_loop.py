"""AV loop restart behavior via AppController."""
from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml

from blaster.app import AppController


class TestMainAVLoop(unittest.IsolatedAsyncioTestCase):
    async def test_av_loop_restarts_on_error(self):
        tmp = Path(self._tmp_config())
        call_count = 0

        async def fake_stream():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Stream failed!")
            elif call_count == 2:
                yield (True, False)
                await asyncio.Future()

        with (
            patch("blaster.app.IRBlasterBLE") as mock_IRBlasterBLE,
            patch("blaster.app.get_initial_state", return_value=(False, False)),
            patch("blaster.app.stream_av_events", side_effect=fake_stream),
            patch("blaster.app.execute_specs", new_callable=AsyncMock),
        ):
            mock_ble = MagicMock()
            mock_ble.connect = AsyncMock(return_value=True)
            mock_ble.wait_until_ready = AsyncMock()
            mock_ble.schedule_disconnect_command = AsyncMock()
            mock_ble.send_heartbeat = AsyncMock()
            mock_ble.disconnect = AsyncMock()
            mock_ble.is_connected = True
            mock_ble.set_disconnect_callback = MagicMock()
            mock_IRBlasterBLE.return_value = mock_ble

            ctrl = AppController(tmp)
            await ctrl.start()
            await asyncio.sleep(1.5)
            await ctrl.stop()

        self.assertGreaterEqual(call_count, 2)

    def _tmp_config(self) -> str:
        import tempfile

        path = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.safe_dump(
            {
                "ble": {"device_name": "Test"},
                "events": {
                    "OnConnect": [{"NamedCommand": "On", "Delay": 0}],
                    "OnDisconnect": [
                        {"NamedCommand": "Off", "Delay": 900}
                    ],
                    "Active": [{"NamedCommand": "Red"}],
                    "Idle": [{"NamedCommand": "Green", "Delay": 120}],
                },
            },
            path,
        )
        path.close()
        return path.name


if __name__ == "__main__":
    unittest.main()

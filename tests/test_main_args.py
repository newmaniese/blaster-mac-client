import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blaster.__main__ import main


def _run_coroutine(coro):
    """Drive patched asyncio.run in sync tests so AsyncMock coroutines are awaited."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestMainArgs(unittest.TestCase):
    @patch("blaster.__main__.run")
    def test_main_with_config(self, mock_run):
        test_config = Path("/tmp/custom_config.yaml")
        with patch("sys.argv", ["blaster", "--config", str(test_config)]):
            with patch("asyncio.run", side_effect=_run_coroutine):
                main()
                mock_run.assert_called_once_with(config_path=test_config)

    @patch("blaster.__main__.run")
    def test_main_default(self, mock_run):
        with patch("sys.argv", ["blaster"]):
            with patch("asyncio.run", side_effect=_run_coroutine):
                main()
                mock_run.assert_called_once_with(config_path=None)

if __name__ == '__main__':
    unittest.main()

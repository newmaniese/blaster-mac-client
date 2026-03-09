
import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blaster.__main__ import main

class TestMainArgs(unittest.TestCase):
    @patch('blaster.__main__.run')
    def test_main_with_config(self, mock_run):
        test_config = Path('/tmp/custom_config.yaml')
        with patch('sys.argv', ['blaster', '--config', str(test_config)]):
            with patch('asyncio.run') as mock_asyncio_run:
                main()
                mock_run.assert_called_once_with(config_path=test_config)

    @patch('blaster.__main__.run')
    def test_main_default(self, mock_run):
        with patch('sys.argv', ['blaster']):
            with patch('asyncio.run') as mock_asyncio_run:
                main()
                mock_run.assert_called_once_with(config_path=None)

if __name__ == '__main__':
    unittest.main()

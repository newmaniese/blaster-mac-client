import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blaster.logging_setup import (
    LOG_FILENAME,
    configure_logging,
    parse_log_level,
)


class TestParseLogLevel(unittest.TestCase):
    def test_default_info(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(parse_log_level(None), logging.INFO)

    def test_env_override(self):
        with patch.dict("os.environ", {"BLASTER_LOG_LEVEL": "debug"}):
            self.assertEqual(parse_log_level(None), logging.DEBUG)

    def test_explicit_beats_env(self):
        with patch.dict("os.environ", {"BLASTER_LOG_LEVEL": "DEBUG"}):
            self.assertEqual(parse_log_level("WARNING"), logging.WARNING)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_log_level("LOUD")


class TestConfigureLogging(unittest.TestCase):
    def test_creates_rotating_file_and_quiets_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            path = configure_logging("INFO", log_dir=log_dir, console=False)
            self.assertEqual(path, log_dir / LOG_FILENAME)
            self.assertTrue(path.exists())

            logging.getLogger("blaster").info("hello from blaster")
            logging.getLogger("aiohttp.access").info("should not appear")
            for handler in logging.getLogger().handlers:
                handler.flush()

            text = path.read_text(encoding="utf-8")
            self.assertIn("hello from blaster", text)
            self.assertNotIn("should not appear", text)
            self.assertEqual(logging.getLogger("aiohttp.access").level, logging.WARNING)


if __name__ == "__main__":
    unittest.main()

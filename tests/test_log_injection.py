import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from blaster.utils import execute_specs, sanitize_log_message
from blaster.config import EventSpec

class TestLogInjection(unittest.IsolatedAsyncioTestCase):
    def test_sanitize_log_message(self):
        self.assertEqual(sanitize_log_message("OK"), "OK")
        self.assertEqual(sanitize_log_message("OK\nFORGED"), "OK\\nFORGED")
        self.assertEqual(sanitize_log_message("OK\rFORGED"), "OK\\rFORGED")
        self.assertEqual(sanitize_log_message("OK\r\nFORGED"), "OK\\r\\nFORGED")
        self.assertEqual(sanitize_log_message(Exception("Error\nMessage")), "Error\\nMessage")

    @patch("blaster.utils.logger")
    async def test_execute_specs_sanitization(self, mock_logger):
        ble = MagicMock()
        ble.send_command_by_name = AsyncMock(return_value="OK\nFORGED")

        specs = [EventSpec(NamedCommand="PowerOn", Delay=0)]

        await execute_specs(ble, specs, context="test")

        # Verify that the log message contains the escaped newline
        mock_logger.info.assert_called_once()
        args, _ = mock_logger.info.call_args
        self.assertIn("OK\\nFORGED", args[3])

    @patch("blaster.utils.logger")
    async def test_execute_specs_exception_sanitization(self, mock_logger):
        ble = MagicMock()
        ble.send_command_by_name = AsyncMock(side_effect=Exception("Failed\r\nInject"))

        specs = [EventSpec(NamedCommand="PowerOn", Delay=0)]

        await execute_specs(ble, specs, context="test")

        # Verify that the warning log message contains the escaped CRLF
        mock_logger.warning.assert_called_once()
        args, _ = mock_logger.warning.call_args
        self.assertIn("Failed\\r\\nInject", args[3])

if __name__ == "__main__":
    unittest.main()

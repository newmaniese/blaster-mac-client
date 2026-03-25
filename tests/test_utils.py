import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from blaster.config import EventSpec
from blaster.utils import execute_specs


class TestExecuteSpecs(unittest.IsolatedAsyncioTestCase):
    async def test_execute_specs_basic(self):
        """Test executing a list of specs with delays and commands."""
        ble = AsyncMock()
        ble.send_command_by_name.return_value = "OK"

        specs = [
            EventSpec(NamedCommand="Cmd1", Delay=0),
            EventSpec(NamedCommand="Cmd2", Delay=5),
        ]

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await execute_specs(ble, specs, context="test")

        # Check calls
        assert ble.send_command_by_name.call_count == 2
        ble.send_command_by_name.assert_any_call("Cmd1")
        ble.send_command_by_name.assert_any_call("Cmd2")

        # Check delays
        mock_sleep.assert_called_once_with(5)

    async def test_execute_specs_exception_handling(self):
        """Test that exceptions during command execution are caught and logged."""
        ble = AsyncMock()
        ble.send_command_by_name.side_effect = [Exception("Fail"), "OK"]

        specs = [
            EventSpec(NamedCommand="Cmd1"),
            EventSpec(NamedCommand="Cmd2"),
        ]

        # Patch logger to verify warnings
        with patch("blaster.utils.logger") as mock_logger:
            await execute_specs(ble, specs, context="error_test")

        # Both commands should be attempted
        assert ble.send_command_by_name.call_count == 2

        # Verify logger usage
        mock_logger.warning.assert_called_once()
        args, _ = mock_logger.warning.call_args
        # args[0] is format string, args[1:] are arguments
        formatted_msg = args[0] % args[1:]
        self.assertIn("Cmd1 (error_test) failed: Fail", formatted_msg)

    async def test_execute_specs_no_context(self):
        """Test execution without context string."""
        ble = AsyncMock()
        ble.send_command_by_name.return_value = "OK"
        specs = [EventSpec(NamedCommand="Cmd1")]

        with patch("blaster.utils.logger") as mock_logger:
            await execute_specs(ble, specs)  # context defaults to ""

        ble.send_command_by_name.assert_called_once_with("Cmd1")
        mock_logger.info.assert_called_once()
        args, _ = mock_logger.info.call_args
        # Expected: "Sent %s%s -> %s" with args ("Cmd1", "", "OK")
        self.assertEqual(args[1], "Cmd1")
        self.assertEqual(args[2], "")
        self.assertEqual(args[3], "OK")


class TestLogInjectionSanitization(unittest.IsolatedAsyncioTestCase):
    async def test_log_injection_sanitization(self) -> None:
        ble = AsyncMock()
        malicious_status = (
            "OK\n[2023-01-01 00:00:00] INFO blaster.utils: Sent AdminCmd (test) -> OK"
        )
        ble.send_command_by_name.return_value = malicious_status

        specs = [EventSpec(NamedCommand="Cmd1\rLogInjection", Delay=0)]

        with patch("blaster.utils.logger") as mock_logger:
            await execute_specs(ble, specs, context="test\ncontext")

            mock_logger.info.assert_called_once()
            args, _ = mock_logger.info.call_args
            self.assertNotIn("\n", args[1])
            self.assertNotIn("\r", args[1])
            self.assertIn("\\r", args[1])
            self.assertNotIn("\n", args[2])
            self.assertIn("\\n", args[2])
            self.assertNotIn("\n", args[3])
            self.assertIn("\\n", args[3])

    async def test_non_string_status(self) -> None:
        ble = AsyncMock()
        ble.send_command_by_name.return_value = 200
        specs = [EventSpec(NamedCommand="Cmd1")]

        with patch("blaster.utils.logger") as mock_logger:
            await execute_specs(ble, specs)

            args, _ = mock_logger.info.call_args
            self.assertEqual(args[3], "200")

    async def test_exception_sanitization(self) -> None:
        ble = AsyncMock()
        ble.send_command_by_name.side_effect = Exception("Error\nMessage")
        specs = [EventSpec(NamedCommand="Cmd1")]

        with patch("blaster.utils.logger") as mock_logger:
            await execute_specs(ble, specs)

            mock_logger.warning.assert_called_once()
            args, _ = mock_logger.warning.call_args
            self.assertNotIn("\n", args[3])
            self.assertIn("Error\\nMessage", args[3])

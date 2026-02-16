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
        # "Send %s%s failed: %s"
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

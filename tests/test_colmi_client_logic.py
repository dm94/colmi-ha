import sys
from unittest.mock import MagicMock

# Mocking modules that might not be present
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.const"] = MagicMock()
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.exceptions"] = MagicMock()
sys.modules["homeassistant.helpers.update_coordinator"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.bluetooth"] = MagicMock()
sys.modules["bleak"] = MagicMock()
sys.modules["bleak.exc"] = MagicMock()
sys.modules["bleak_retry_connector"] = MagicMock()

import unittest
# Import from colmi_client directly to avoid importing __init__.py which imports coordinator
from custom_components.colmi_r09.colmi_client import ColmiRingClient, MeasurementState
from custom_components.colmi_r09.const import (
    CMD_START_REAL_TIME,
    REALTIME_CMD_START,
    REALTIME_CMD_CONTINUE,
    REALTIME_CMD_STOP,
    MTYPE_HR,
    MTYPE_BP,
)

class TestColmiClientLogic(unittest.TestCase):
    def setUp(self):
        self.ble_device = MagicMock()
        self.ble_device.address = "AA:BB:CC:DD:EE:FF"
        self.client = ColmiRingClient(self.ble_device)

    def test_checksum(self):
        packet = bytearray([0x01] * 16)
        # Sum of first 15 bytes is 15. 15 & 255 = 15.
        expected_checksum = 15
        self.assertEqual(self.client._checksum(packet), expected_checksum)

    def test_build_realtime_start_packet(self):
        packet = self.client._build_realtime_start_packet(MTYPE_HR)
        self.assertEqual(packet[0], CMD_START_REAL_TIME)
        self.assertEqual(packet[1], MTYPE_HR)
        self.assertEqual(packet[2], REALTIME_CMD_START)
        self.assertEqual(packet[15], self.client._checksum(packet))

    def test_build_realtime_continue_packet(self):
        packet = self.client._build_realtime_continue_packet(MTYPE_HR)
        self.assertEqual(packet[0], CMD_START_REAL_TIME)
        self.assertEqual(packet[1], MTYPE_HR)
        self.assertEqual(packet[2], REALTIME_CMD_CONTINUE)
        self.assertEqual(packet[15], self.client._checksum(packet))

    def test_build_realtime_stop_packet(self):
        packet = self.client._build_realtime_stop_packet(MTYPE_HR)
        self.assertEqual(packet[0], CMD_START_REAL_TIME)
        self.assertEqual(packet[1], MTYPE_HR)
        self.assertEqual(packet[2], REALTIME_CMD_STOP)
        self.assertEqual(packet[15], self.client._checksum(packet))

    def test_handle_realtime_response_success(self):
        state = MeasurementState()
        # Packet: [CMD, MTYPE, ERROR_CODE, VALUE, ...]
        data = bytearray([0] * 16)
        data[0] = CMD_START_REAL_TIME
        data[1] = MTYPE_HR
        data[2] = 0 # Success
        data[3] = 75 # HR value
        data[15] = self.client._checksum(data)

        self.client._handle_realtime_response(data, MTYPE_HR, state)
        self.assertEqual(state.value, 75)
        self.assertEqual(state.error_code, 0)
        self.assertEqual(state.valid_readings, 1)

    def test_handle_realtime_response_error(self):
        state = MeasurementState()
        data = bytearray([0] * 16)
        data[0] = CMD_START_REAL_TIME
        data[1] = MTYPE_HR
        data[2] = 5 # Some error code
        data[15] = self.client._checksum(data)

        self.client._handle_realtime_response(data, MTYPE_HR, state)
        self.assertIsNone(state.value)
        self.assertEqual(state.error_code, 5)
        self.assertEqual(state.valid_readings, 0)

    def test_handle_notification_mtype_mismatch(self):
        self.client._current_mtype = MTYPE_HR
        self.client._current_realtime_state = MeasurementState()

        # Packet for BP while waiting for HR
        data = bytearray([0] * 16)
        data[0] = CMD_START_REAL_TIME
        data[1] = MTYPE_BP
        data[2] = 0
        data[15] = self.client._checksum(data)

        initial_update_time = self.client._current_realtime_state.last_update
        self.client._handle_notification(None, data)

        # Should not have updated state
        self.assertEqual(self.client._current_realtime_state.observation_count, 0)
        self.assertEqual(self.client._current_realtime_state.last_update, initial_update_time)

if __name__ == "__main__":
    unittest.main()

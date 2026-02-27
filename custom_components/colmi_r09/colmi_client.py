"""BLE client for the Colmi R09 Smart Ring.

Handles all low-level Bluetooth communication: connecting to the ring,
building command packets, parsing response packets, and extracting
sensor values (heart rate, SpO2, blood pressure, temperature, HRV,
stress, blood sugar, and battery level).

Protocol summary (Nordic UART-like BLE):
- Service UUID  : 6E40FFF0-B5A3-F393-E0A9-E50E24DCCA9E
- RX (write)    : 6E400002-B5A3-F393-E0A9-E50E24DCCA9E
- TX (notify)   : 6E400003-B5A3-F393-E0A9-E50E24DCCA9E

Packet format (16 bytes):
  [0]      Command byte
  [1..14]  Payload (sub-command / data)
  [15]     Checksum = (sum of bytes 0..14) % 255
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from .const import (
    MEASUREMENT_STABLE_PERIOD,
    MEASUREMENT_TIMEOUT,
    MTYPE_BP,
    MTYPE_BLOOD_SUGAR,
    MTYPE_HR,
    MTYPE_HRV,
    MTYPE_SPO2,
    MTYPE_STRESS,
    MTYPE_TEMP,
    CMD_BATTERY,
    CMD_REALTIME,
    KEY_BATTERY,
    KEY_BLOOD_SUGAR,
    KEY_BP_DIASTOLIC,
    KEY_BP_SYSTOLIC,
    KEY_HEART_RATE,
    KEY_HRV,
    KEY_SPO2,
    KEY_STRESS,
    KEY_TEMPERATURE,
    PACKET_SIZE,
    REALTIME_CMD_START,
    REALTIME_CMD_STOP,
    RX_CHAR_UUID,
    TX_CHAR_UUID,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class MeasurementState:
    """Tracks the rolling state of an in-progress measurement."""
    value: Any = None
    value2: Any = None  # Used for blood pressure (diastolic)
    last_update: float = field(default_factory=time.monotonic)
    observation_count: int = 0


class ColmiRingClient:
    """Async BLE client for the Colmi R09 smart ring.

    Usage::

        client = ColmiRingClient(ble_device)
        data = await client.collect_all_data()
    """

    def __init__(self, ble_device) -> None:
        """Initialise with a BLE device object (from bleak scan)."""
        self._ble_device = ble_device
        self._address: str = ble_device.address
        self._client: BleakClient | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def collect_all_data(self) -> dict[str, Any]:
        """Connect to the ring and collect all available sensor data.

        Returns a dict with all available readings. Missing values are None.
        Each measurement requires a separate connection (ring limitation).
        """
        result: dict[str, Any] = {
            KEY_BATTERY: None,
            KEY_HEART_RATE: None,
            KEY_SPO2: None,
            KEY_BP_SYSTOLIC: None,
            KEY_BP_DIASTOLIC: None,
            KEY_TEMPERATURE: None,
            KEY_HRV: None,
            KEY_STRESS: None,
            KEY_BLOOD_SUGAR: None,
        }

        measurements = [
            (KEY_HEART_RATE, MTYPE_HR),
            (KEY_SPO2, MTYPE_SPO2),
            (KEY_STRESS, MTYPE_STRESS),
            (KEY_HRV, MTYPE_HRV),
            (KEY_TEMPERATURE, MTYPE_TEMP),
            (KEY_BP_SYSTOLIC, MTYPE_BP),
            (KEY_BLOOD_SUGAR, MTYPE_BLOOD_SUGAR),
        ]

        # --- Battery (one connection) ---
        try:
            battery = await self._run_battery_measurement()
            result[KEY_BATTERY] = battery
        except Exception as err:
            _LOGGER.warning("Battery measurement failed: %s", err)

        # --- Health metrics (one connection each, as required by ring) ---
        for key, mtype in measurements:
            try:
                values = await self._run_realtime_measurement(mtype)
                if mtype == MTYPE_BP:
                    result[KEY_BP_SYSTOLIC] = values[0] if values else None
                    result[KEY_BP_DIASTOLIC] = values[1] if values and len(values) > 1 else None
                else:
                    result[key] = values[0] if values else None
            except Exception as err:
                _LOGGER.warning("Measurement %s failed: %s", key, err)

        return result

    # ------------------------------------------------------------------
    # Battery measurement
    # ------------------------------------------------------------------

    async def _run_battery_measurement(self) -> int | None:
        """Connect, read battery level, disconnect."""
        async with await self._connect() as client:
            battery_value: int | None = None
            event = asyncio.Event()

            def notification_handler(sender, data: bytearray) -> None:
                nonlocal battery_value
                if len(data) >= 4 and data[0] == CMD_BATTERY:
                    battery_value = int(data[1])
                    event.set()

            await client.start_notify(TX_CHAR_UUID, notification_handler)
            await client.write_gatt_char(
                RX_CHAR_UUID,
                self._build_packet(CMD_BATTERY),
                response=True,
            )
            try:
                await asyncio.wait_for(event.wait(), timeout=10)
            except asyncio.TimeoutError:
                _LOGGER.debug("Timeout waiting for battery response")
            finally:
                try:
                    await client.stop_notify(TX_CHAR_UUID)
                except Exception:
                    pass

        return battery_value

    # ------------------------------------------------------------------
    # Real-time measurement
    # ------------------------------------------------------------------

    async def _run_realtime_measurement(self, mtype: int) -> list[Any]:
        """Connect, request a real-time measurement, wait for stable data, disconnect."""
        state = MeasurementState()
        stable_event = asyncio.Event()

        async with await self._connect() as client:
            def notification_handler(sender, data: bytearray) -> None:
                self._handle_realtime_response(data, mtype, state)
                state.last_update = time.monotonic()
                state.observation_count += 1

            await client.start_notify(TX_CHAR_UUID, notification_handler)

            # Send START command
            start_packet = self._build_realtime_packet(mtype, REALTIME_CMD_START)
            await client.write_gatt_char(RX_CHAR_UUID, start_packet, response=True)

            # Wait until data stream has been stable for MEASUREMENT_STABLE_PERIOD seconds
            deadline = time.monotonic() + MEASUREMENT_TIMEOUT
            while time.monotonic() < deadline:
                await asyncio.sleep(1)
                elapsed_since_update = time.monotonic() - state.last_update
                if (
                    state.observation_count > 0
                    and state.value is not None
                    and elapsed_since_update >= MEASUREMENT_STABLE_PERIOD
                ):
                    _LOGGER.debug(
                        "Stable measurement for mtype=0x%02X: %s (after %d observations)",
                        mtype, state.value, state.observation_count,
                    )
                    break

            # Send STOP command
            try:
                stop_packet = self._build_realtime_packet(mtype, REALTIME_CMD_STOP)
                await client.write_gatt_char(RX_CHAR_UUID, stop_packet, response=True)
            except Exception:
                pass

            try:
                await client.stop_notify(TX_CHAR_UUID)
            except Exception:
                pass

        results: list[Any] = []
        if state.value is not None:
            results.append(state.value)
        if state.value2 is not None:
            results.append(state.value2)
        return results

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _handle_realtime_response(
        self, data: bytearray, mtype: int, state: MeasurementState
    ) -> None:
        """Parse a notification packet and update state with the latest reading."""
        if len(data) < PACKET_SIZE:
            return
        if data[0] != CMD_REALTIME:
            return
        if data[1] != mtype:
            return

        # The payload layout varies per measurement type
        # Based on the Toit/colmi_r02_client reverse-engineering:
        if mtype == MTYPE_HR:
            # data[3] = heart rate value (bpm), 0 means measuring in progress
            value = int(data[3])
            if value > 0:
                state.value = value

        elif mtype == MTYPE_SPO2:
            # data[3] = SpO2 percentage, 0 means in progress
            value = int(data[3])
            if value > 0:
                state.value = value

        elif mtype == MTYPE_STRESS:
            # data[3] = stress level (0-100)
            value = int(data[3])
            if value > 0:
                state.value = value

        elif mtype == MTYPE_HRV:
            # data[3] + data[4] = HRV in ms (big-endian uint16)
            raw = (int(data[3]) << 8) | int(data[4])
            if raw > 0:
                state.value = raw

        elif mtype == MTYPE_TEMP:
            # data[3] and data[4] encode temperature as a fixed-point number
            # Integer part in data[3], decimal part in data[4]
            integer_part = int(data[3])
            decimal_part = int(data[4])
            if integer_part > 0:
                state.value = round(integer_part + decimal_part / 10.0, 1)

        elif mtype == MTYPE_BP:
            # data[3] = systolic, data[4] = diastolic (mmHg)
            systolic = int(data[3])
            diastolic = int(data[4])
            if systolic > 0 and diastolic > 0:
                state.value = systolic
                state.value2 = diastolic

        elif mtype == MTYPE_BLOOD_SUGAR:
            # data[3] + data[4] = blood sugar in mg/dL (big-endian uint16)
            raw = (int(data[3]) << 8) | int(data[4])
            if raw > 0:
                state.value = raw

    # ------------------------------------------------------------------
    # Packet building
    # ------------------------------------------------------------------

    @staticmethod
    def _checksum(packet: bytearray) -> int:
        """Calculate the packet checksum: sum of first 15 bytes mod 255."""
        return sum(packet[:PACKET_SIZE - 1]) % 255

    def _build_packet(self, command: int, payload: bytes | None = None) -> bytearray:
        """Build a 16-byte command packet."""
        packet = bytearray(PACKET_SIZE)
        packet[0] = command
        if payload:
            for i, b in enumerate(payload[:PACKET_SIZE - 2]):
                packet[i + 1] = b
        packet[PACKET_SIZE - 1] = self._checksum(packet)
        return packet

    def _build_realtime_packet(self, mtype: int, cmd: int) -> bytearray:
        """Build a real-time measurement start/stop packet."""
        # Payload: [mtype, cmd, 0x00 ...]
        payload = bytearray([mtype, cmd])
        return self._build_packet(CMD_REALTIME, payload)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def _connect(self) -> BleakClient:
        """Establish a connection using bleak-retry-connector."""
        _LOGGER.debug("Connecting to Colmi R09 at %s", self._address)
        client = await establish_connection(
            BleakClient,
            self._ble_device,
            self._address,
            max_attempts=8,
        )
        return client

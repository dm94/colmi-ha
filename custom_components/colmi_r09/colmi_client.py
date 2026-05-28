"""BLE client for the Colmi R09 Smart Ring.

Handles all low-level Bluetooth communication: connecting to the ring,
building command packets, parsing response packets, and extracting
sensor values (heart rate, SpO2, blood pressure, temperature, HRV,
stress, and battery level).

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
    CONNECTION_TIMEOUT,
    MEASUREMENT_PAUSE,
    MEASUREMENT_STABLE_PERIOD,
    MEASUREMENT_TIMEOUT,
    MTYPE_BP,
    MTYPE_HR,
    MTYPE_HRV,
    MTYPE_SPO2,
    MTYPE_STRESS,
    MTYPE_TEMP,
    MAX_CONNECTION_ATTEMPTS,
    CMD_BATTERY,
    CMD_START_REAL_TIME,
    REALTIME_CMD_STOP,
    KEY_BATTERY,
    KEY_BP_DIASTOLIC,
    KEY_BP_SYSTOLIC,
    KEY_HEART_RATE,
    KEY_HRV,
    KEY_SPO2,
    KEY_STRESS,
    KEY_TEMPERATURE,
    PACKET_SIZE,
    REALTIME_CMD_CONTINUE,
    REALTIME_CMD_START,
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
    valid_readings: int = 0
    error_code: int = 0


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
        self._battery_event: asyncio.Event | None = None
        self._battery_value: int | None = None
        self._current_mtype: int | None = None
        self._current_realtime_state: MeasurementState | None = None

    def _handle_notification(self, sender: Any, data: bytearray) -> None:
        """Central notification handler for all BLE messages."""
        if len(data) >= 4 and data[0] == CMD_BATTERY:
            _LOGGER.debug("[%s] RECV (battery): %s", self._address, data.hex())
            if self._battery_event:
                self._battery_value = int(data[1])
                self._battery_event.set()
        elif len(data) >= PACKET_SIZE and data[0] == CMD_START_REAL_TIME:
            if (
                self._current_mtype is not None
                and self._current_realtime_state is not None
                and data[1] == self._current_mtype
            ):
                _LOGGER.debug("[%s] RECV (0x%02X): %s", self._address, self._current_mtype, data.hex())
                self._handle_realtime_response(data, self._current_mtype, self._current_realtime_state)
                self._current_realtime_state.last_update = time.monotonic()
                self._current_realtime_state.observation_count += 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def collect_all_data(self) -> tuple[bool, dict[str, Any]]:
        """Connect to the ring and collect all available sensor data.

        Returns (connected, data): connected is True if a BLE connection was
        established; data holds all readings (None where not available).
        Uses a single BLE connection for the entire cycle to avoid saturating
        proxy/adapter connection slots.
        """
        _LOGGER.debug("[%s] Starting full data collection cycle", self._address)
        result: dict[str, Any] = {
            KEY_BATTERY: None,
            KEY_HEART_RATE: None,
            KEY_SPO2: None,
            KEY_TEMPERATURE: None,
            KEY_HRV: None,
            KEY_STRESS: None,
            KEY_BP_SYSTOLIC: None,
            KEY_BP_DIASTOLIC: None,
        }

        # Sequence matches the reference implementation (Toit sequence)
        measurements = [
            (KEY_HEART_RATE, MTYPE_HR),
            (KEY_SPO2, MTYPE_SPO2),
            (KEY_TEMPERATURE, MTYPE_TEMP),
            (KEY_HRV, MTYPE_HRV),
            (KEY_STRESS, MTYPE_STRESS),
            (None, MTYPE_BP),
        ]

        # Single connection for entire cycle — reduces proxy slot exhaustion
        client = None
        connected = False
        try:
            client = await self._connect()
            
            # Ensure characteristics exist before notifying
            try:
                services = getattr(client, "services", None)
                if services is None:
                    services = await client.get_services()

                tx_char = None
                for service in services:
                    for char in service.characteristics:
                        if str(char.uuid).lower() == TX_CHAR_UUID:
                            tx_char = char
                            break
                    if tx_char:
                        break

                if not tx_char:
                    _LOGGER.error("[%s] TX characteristic %s not found", self._address, TX_CHAR_UUID)
                    raise BleakError(f"TX characteristic {TX_CHAR_UUID} not found")

                _LOGGER.debug("[%s] Enabling notifications on TX_CHAR_UUID=%s", self._address, TX_CHAR_UUID)
                await client.start_notify(tx_char, self._handle_notification)
                connected = True
            except Exception as notify_err:
                _LOGGER.error("[%s] Failed to start notifications: %s", self._address, notify_err)
                raise
            
            # --- Battery ---
            try:
                result[KEY_BATTERY] = await self._run_battery_measurement(client)
            except Exception as err:
                _LOGGER.warning("Battery measurement failed: %s", err)

            # --- Health metrics (sequential on same connection) ---
            for key, mtype in measurements:
                try:
                    await asyncio.sleep(MEASUREMENT_PAUSE)
                    _LOGGER.debug(
                        "[%s] Starting measurement for key=%s (mtype=0x%02X)",
                        self._address,
                        key,
                        mtype,
                    )
                    values = await self._run_realtime_measurement(mtype, client)
                    if mtype == MTYPE_BP:
                        result[KEY_BP_SYSTOLIC] = values[0] if len(values) > 0 else None
                        result[KEY_BP_DIASTOLIC] = values[1] if len(values) > 1 else None
                    elif key:
                        result[key] = values[0] if values else None
                except Exception as err:
                    _LOGGER.warning("Measurement %s failed: %s", key or mtype, err)
                    
            try:
                await client.stop_notify(TX_CHAR_UUID)
            except Exception:
                pass
                
        except Exception as err:
            err_str = str(err)
            _LOGGER.warning("[%s] Connection failed for full cycle: %s", self._address, err)
            if "connection slot" in err_str.lower() or "out of connection slots" in err_str.lower():
                _LOGGER.info(
                    "[%s] Bluetooth proxy has no free slots. Add more proxies near the ring or "
                    "increase scan interval: https://esphome.github.io/bluetooth-proxies/",
                    self._address,
                )
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass

        _LOGGER.debug("[%s] Full data collection result: connected=%s, data=%s", self._address, connected, result)
        return (connected, result)

    # ------------------------------------------------------------------
    # Battery measurement
    # ------------------------------------------------------------------

    async def _run_battery_measurement(self, client: BleakClient) -> int | None:
        """Read battery level using an existing BLE connection."""
        self._battery_event = asyncio.Event()
        self._battery_value = None

        packet = self._build_packet(CMD_BATTERY)
        _LOGGER.debug("[%s] SEND (battery) to RX_CHAR_UUID=%s: %s", self._address, RX_CHAR_UUID, packet.hex())
        try:
            await client.write_gatt_char(
                RX_CHAR_UUID,
                packet,
                response=False,
            )
        except Exception as err:
            _LOGGER.warning(
                "[%s] write_gatt_char failed for battery on RX_CHAR_UUID=%s: %s",
                self._address,
                RX_CHAR_UUID,
                err,
            )
            raise
        try:
            await asyncio.wait_for(self._battery_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            _LOGGER.debug("Timeout waiting for battery response")
        finally:
            self._battery_event = None

        return self._battery_value

    # ------------------------------------------------------------------
    # Real-time measurement
    # ------------------------------------------------------------------

    async def _run_realtime_measurement(self, mtype: int, client: BleakClient) -> list[Any]:
        """Request a real-time measurement using an existing BLE connection."""
        state = MeasurementState()
        self._current_mtype = mtype
        self._current_realtime_state = state

        try:
            # Send START command
            start_packet = self._build_realtime_start_packet(mtype)
            _LOGGER.debug(
                "[%s] SEND START (0x%02X) to RX_CHAR_UUID=%s: %s",
                self._address,
                mtype,
                RX_CHAR_UUID,
                start_packet.hex(),
            )
            await client.write_gatt_char(RX_CHAR_UUID, start_packet, response=False)

            # The measurement is complete when data stops arriving (silence) or error received.
            deadline = time.monotonic() + MEASUREMENT_TIMEOUT
            last_continue = 0.0
            while time.monotonic() < deadline:
                # Periodic CONTINUE packet (every 2 seconds)
                now = time.monotonic()
                if now - last_continue >= 2.0:
                    continue_packet = self._build_realtime_continue_packet(mtype)
                    _LOGGER.debug("[%s] SEND CONTINUE (0x%02X)", self._address, mtype)
                    await client.write_gatt_char(RX_CHAR_UUID, continue_packet, response=False)
                    last_continue = now

                await asyncio.sleep(1)

                if state.error_code != 0:
                    _LOGGER.warning("[%s] Measurement 0x%02X aborted with error code: %d", self._address, mtype, state.error_code)
                    break

                silence_duration = time.monotonic() - state.last_update
                if state.observation_count > 0 and silence_duration >= MEASUREMENT_STABLE_PERIOD:
                    _LOGGER.debug(
                        "Measurement stable for mtype=0x%02X after %d observations and %.1fs of silence",
                        mtype, state.observation_count, silence_duration
                    )
                    break
        except Exception as err:
            _LOGGER.warning(
                "[%s] Error during realtime measurement mtype=0x%02X: %s",
                self._address,
                mtype,
                err,
            )
            raise
        finally:
            # Send STOP command
            try:
                stop_packet = self._build_realtime_stop_packet(mtype)
                _LOGGER.debug("[%s] SEND STOP (0x%02X)", self._address, mtype)
                await client.write_gatt_char(RX_CHAR_UUID, stop_packet, response=False)
            except Exception as stop_err:
                _LOGGER.debug("[%s] Failed to send STOP for 0x%02X: %s", self._address, mtype, stop_err)

            self._current_mtype = None
            self._current_realtime_state = None

        if state.value is None and state.value2 is None:
            _LOGGER.debug(
                "[%s] Measurement finished for mtype=0x%02X after %d observations, no stable value",
                self._address,
                mtype,
                state.observation_count,
            )

        results: list[Any] = []
        if state.value is not None:
            results.append(state.value)
        if state.value2 is not None:
            results.append(state.value2)
        _LOGGER.debug(
            "[%s] Measurement finished for mtype=0x%02X with results=%s",
            self._address,
            mtype,
            results,
        )
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
        if data[0] != CMD_START_REAL_TIME:
            return
        if data[1] != mtype:
            return

        error_code = data[2]
        if error_code != 0:
            state.error_code = error_code
            return

        # The payload layout varies per measurement type
        # Based on the Toit/colmi_r02_client reverse-engineering:
        if mtype == MTYPE_HR:
            # data[3] = heart rate value (bpm), 0 means measuring in progress
            value = int(data[3])
            if value > 0:
                state.value = value
                state.valid_readings += 1

        elif mtype == MTYPE_SPO2:
            # data[3] = SpO2 percentage, 0 means in progress
            value = int(data[3])
            if value > 0:
                state.value = value
                state.valid_readings += 1

        elif mtype == MTYPE_STRESS:
            # data[3] = stress level (fatigue)
            # Reference: response = response >> 1
            value = int(data[3])
            if value > 0:
                state.value = value >> 1
                state.valid_readings += 1

        elif mtype == MTYPE_HRV:
            # data[3] = HRV in ms
            value = int(data[3])
            if value > 0:
                state.value = value
                state.valid_readings += 1

        elif mtype == MTYPE_TEMP:
            # data[3] encodes temperature
            # Reference: response = response < 11 ? 0 : response.to_float/10 + 20
            value = int(data[3])
            if value >= 11:
                state.value = round(value / 10.0 + 20.0, 1)
                state.valid_readings += 1

        elif mtype == MTYPE_BP:
            # data[3] = diastolic, data[4] = systolic
            # Based on Reference: systolic := value[4] & 0xff, response := value[3] & 0xff
            diastolic = int(data[3])
            systolic = int(data[4])
            if systolic > 0 and diastolic > 0:
                state.value = systolic
                state.value2 = diastolic
                state.valid_readings += 1



    # ------------------------------------------------------------------
    # Packet building
    # ------------------------------------------------------------------

    @staticmethod
    def _checksum(packet: bytearray) -> int:
        """Calculate the packet checksum: sum of first 15 bytes mod 255."""
        return sum(packet[:PACKET_SIZE - 1]) & 255

    def _build_packet(self, command: int, payload: bytes | None = None) -> bytearray:
        """Build a 16-byte command packet."""
        packet = bytearray(PACKET_SIZE)
        packet[0] = command
        if payload:
            for i, b in enumerate(payload[:PACKET_SIZE - 2]):
                packet[i + 1] = b
        packet[PACKET_SIZE - 1] = self._checksum(packet)
        return packet

    def _build_realtime_start_packet(self, mtype: int) -> bytearray:
        """Build a real-time measurement start packet."""
        # Payload: [mtype, REALTIME_CMD_START, 0x00 ...]
        payload = bytearray([mtype, REALTIME_CMD_START])
        return self._build_packet(CMD_START_REAL_TIME, payload)

    def _build_realtime_continue_packet(self, mtype: int) -> bytearray:
        """Build a real-time measurement continue packet."""
        payload = bytearray([mtype, REALTIME_CMD_CONTINUE])
        return self._build_packet(CMD_START_REAL_TIME, payload)

    def _build_realtime_stop_packet(self, mtype: int) -> bytearray:
        """Build a real-time measurement stop packet."""
        payload = bytearray([mtype, REALTIME_CMD_STOP])
        return self._build_packet(CMD_START_REAL_TIME, payload)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def _connect(self) -> BleakClient:
        """Establish a connection using bleak-retry-connector."""
        _LOGGER.debug("[%s] Attempting to connect to Colmi R09...", self._address)
        client = await establish_connection(
            BleakClient,
            self._ble_device,
            self._address,
            max_attempts=MAX_CONNECTION_ATTEMPTS,
            timeout=CONNECTION_TIMEOUT,
        )
        _LOGGER.debug("[%s] Successfully connected!", self._address)

        # Diagnóstico extra: listar servicios y características BLE para comprobar
        # que los UUID RX/TX configurados existen en este dispositivo concreto.
        # En Home Assistant el cliente real suele ser un `HaBleakClientWrapper`,
        # que no siempre expone el método `get_services`, pero sí una propiedad
        # `services`. Para evitar errores de atributo usamos ambas opciones de
        # forma defensiva.
        try:
            services = getattr(client, "services", None)
            if services is None and hasattr(client, "get_services"):
                services = await client.get_services()

            if services is None:
                raise RuntimeError("BLE services not available on client")

            rx_found = False
            tx_found = False
            for service in services:
                _LOGGER.debug("[%s] Service %s", self._address, service.uuid)
                for char in service.characteristics:
                    _LOGGER.debug(
                        "[%s]   Char %s (props=%s)",
                        self._address,
                        char.uuid,
                        char.properties,
                    )
                    if str(char.uuid).lower() == RX_CHAR_UUID:
                        rx_found = True
                    if str(char.uuid).lower() == TX_CHAR_UUID:
                        tx_found = True
            if not rx_found or not tx_found:
                _LOGGER.warning(
                    "[%s] Configured RX/TX characteristics not found on device. "
                    "RX_FOUND=%s TX_FOUND=%s (RX_CHAR_UUID=%s, TX_CHAR_UUID=%s)",
                    self._address,
                    rx_found,
                    tx_found,
                    RX_CHAR_UUID,
                    TX_CHAR_UUID,
                )
        except Exception as err:
            _LOGGER.debug("[%s] Failed to enumerate services/characteristics: %s", self._address, err)

        return client

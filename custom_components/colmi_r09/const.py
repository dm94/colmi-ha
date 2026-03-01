"""Constants for the Colmi R09 Smart Ring integration."""

DOMAIN = "colmi_r09"

# Default polling interval in minutes
DEFAULT_SCAN_INTERVAL = 10
CONF_SCAN_INTERVAL = "scan_interval"

# BLE Service and Characteristic UUIDs
SERVICE_UUID = "6e40fff0-b5a3-f393-e0a9-e50e24dcca9e"
RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # Write to ring
TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # Read from ring (notify)

# Packet size
PACKET_SIZE = 16

# --------------------------------------------------------------------------
# BLE Command bytes
# --------------------------------------------------------------------------
CMD_BATTERY = 0x03          # Request battery level
CMD_START_REAL_TIME = 105   # Start a real-time manual measurement (0x69)
CMD_STOP_REAL_TIME = 106    # Stop a real-time manual measurement (0x6A)

# Sub-command / measurement type bytes sent with CMD_START_REAL_TIME
MTYPE_HR = 0x01             # Heart rate (bpm)
MTYPE_BP = 0x02             # Blood pressure (systolic/diastolic mmHg)
MTYPE_SPO2 = 0x03           # Blood oxygen saturation (%)
MTYPE_STRESS = 0x04         # Stress level / Fatigue (0-100)
MTYPE_TEMP = 0x08           # Temperature (°C)
MTYPE_BLOOD_SUGAR = 0x09    # Blood sugar (mg/dL)
MTYPE_HRV = 0x0A            # Heart rate variability (ms)

# Control bytes within the realtime command
REALTIME_CMD_START = 0x01   # Continue/Start real-time measurement

# Max time to wait for a stable measurement (seconds)
MEASUREMENT_TIMEOUT = 60
# Time after last data packet considered "stable" / done (seconds)
MEASUREMENT_STABLE_PERIOD = 4

# --------------------------------------------------------------------------
# Sensor keys (used in coordinator data dict)
# --------------------------------------------------------------------------
KEY_BATTERY = "battery"
KEY_HEART_RATE = "heart_rate"
KEY_SPO2 = "spo2"
KEY_STRESS = "stress"
KEY_HRV = "hrv"
KEY_TEMPERATURE = "temperature"
KEY_BP_SYSTOLIC = "blood_pressure_systolic"
KEY_BP_DIASTOLIC = "blood_pressure_diastolic"
KEY_BLOOD_SUGAR = "blood_sugar"

# Configuration keys
CONF_ADDRESS = "address"
CONF_NAME = "name"

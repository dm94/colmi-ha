# Colmi R09 Smart Ring — Home Assistant Integration

A custom Home Assistant integration that synchronizes health and fitness data from the **Colmi R09 BLE smart ring** into Home Assistant sensor entities.

> **Note**: This is a community-developed integration and is not affiliated with COLMI.

## Features

The integration exposes the following sensors:

| Sensor | Unit | Description |
|---|---|---|
| Battery | % | Ring battery level |
| Heart Rate | bpm | Real-time heart rate |
| Blood Oxygen (SpO2) | % | Blood oxygen saturation |
| Blood Pressure Systolic | mmHg | Systolic blood pressure |
| Blood Pressure Diastolic | mmHg | Diastolic blood pressure |
| Body Temperature | °C | Wrist skin temperature |
| Heart Rate Variability (HRV) | ms | Beat-to-beat interval variation |
| Stress Level | — | Stress index (0–100) |
| Blood Sugar | mg/dL | Estimated blood glucose |

> ⚠️ **Medical disclaimer**: Sensor readings from the Colmi R09 are for informational purposes only and should not be used for medical diagnosis or treatment.

## Prerequisites

- Home Assistant 2023.8 or newer
- A Bluetooth adapter accessible by Home Assistant (built-in, USB, or via an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html))
- The `bluetooth` integration enabled in Home Assistant
- Colmi R09 smart ring (the protocol is also compatible with R12)

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Click the **⋮** menu → **Custom repositories**
4. Add this repository URL and select **Integration** as the category
5. Search for **Colmi R09** and install it
6. Restart Home Assistant

### Manual

1. Copy the `custom_components/colmi_r09` folder to your HA `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & Integrations → Add Integration**
2. Search for **Colmi R09 Smart Ring**
3. If your ring is nearby, it will be detected automatically — just confirm
4. If not auto-detected, enter the ring's Bluetooth MAC address manually
   - You can find the MAC address using a BLE scanner app (e.g. nRF Connect)
   - The device name looks like `R09_xxxx`

## Polling Interval

Each polling cycle connects to the ring sequentially to measure every metric. This takes approximately **5–8 minutes** due to the ring's measurement process. The default polling interval is **10 minutes** — changing it to less than 5 minutes is not recommended as it may drain the ring battery quickly.

You can change the interval in **Settings → Devices & Integrations → Colmi R09 → Configure**.

## Protocol Reference

- [colmi-r09-r12 (Toit language reference implementation)](https://github.com/mk590901/colmi-r09-r12)
- [colmi_r02_client (Python, compatible protocol)](https://github.com/tahnok/colmi_r02_client)
- [GadgetBridge (Android app with protocol docs)](https://codeberg.org/Freeyourgadget/Gadgetbridge)

## License

MIT

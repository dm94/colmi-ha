"""DataUpdateCoordinator for the Colmi R09 Smart Ring.

Manages periodic BLE polling of the ring and stores the latest sensor readings
in a dict that all sensor entities share.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .colmi_client import ColmiRingClient
from .const import DOMAIN, KEY_BATTERY, KEY_BLOOD_SUGAR, KEY_BP_DIASTOLIC, KEY_BP_SYSTOLIC, KEY_HEART_RATE, KEY_HRV, KEY_SPO2, KEY_STRESS, KEY_TEMPERATURE

_LOGGER = logging.getLogger(__name__)

# The empty/default data dict — all sensors start as None until first poll
EMPTY_DATA: dict[str, Any] = {
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


class ColmiDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator that polls the Colmi R09 ring at a configurable interval.

    All sensor entities read from the shared ``data`` dict.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        name: str,
        update_interval: timedelta,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{address}",
            update_interval=update_interval,
        )
        self._address = address
        self._ring_name = name

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the ring.

        Called automatically by DataUpdateCoordinator at each interval.
        Raises UpdateFailed on unrecoverable errors so HA marks entities unavailable.
        """
        _LOGGER.debug("Starting Colmi R09 data update for %s (%s)", self._ring_name, self._address)

        # Resolve the current BLE device object (may roam between adapters)
        service_info = bluetooth.async_last_service_info(self.hass, self._address, connectable=True)
        if service_info is None:
            raise UpdateFailed(
                f"Colmi R09 ring {self._address} not found nearby. "
                "Make sure the ring is within Bluetooth range."
            )

        ble_device = service_info.device
        client = ColmiRingClient(ble_device)

        try:
            data = await client.collect_all_data()
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Colmi R09: {err}") from err

        _LOGGER.debug("Colmi R09 data update complete: %s", data)
        return data

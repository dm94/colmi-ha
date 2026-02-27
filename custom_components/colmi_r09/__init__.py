"""Home Assistant integration for the Colmi R09 Smart Ring.

Sets up the DataUpdateCoordinator and loads the sensor platform.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import ColmiDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Colmi R09 from a config entry.

    Creates the coordinator and does an initial data fetch (best-effort --
    the ring does not need to be nearby at setup time).
    """
    address: str = entry.data[CONF_ADDRESS]
    name: str = entry.data.get(CONF_NAME, f"Colmi R09 ({address})")
    scan_interval_minutes: int = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    coordinator = ColmiDataUpdateCoordinator(
        hass=hass,
        address=address,
        name=name,
        update_interval=timedelta(minutes=scan_interval_minutes),
    )

    # Do a best-effort first refresh. If the ring is out of range the coordinator
    # will mark entities as unavailable but setup will still succeed. We do NOT
    # use async_config_entry_first_refresh() because that raises ConfigEntryNotReady
    # (and a 500 error in the UI) when the device is not immediately reachable.
    await coordinator.async_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload entry when options (e.g. scan interval) change
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle an options update by reloading the config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok

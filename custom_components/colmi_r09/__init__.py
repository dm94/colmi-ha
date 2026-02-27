"""Home Assistant integration for the Colmi R09 Smart Ring.

Sets up the DataUpdateCoordinator and loads the sensor platform.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

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

    Creates the coordinator, does an initial data fetch, and sets up platforms.
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

    # Attempt the first update. If the ring is not nearby, this will log a
    # warning but NOT block setup — entities will appear as unavailable and
    # retry on the next polling cycle.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Re-create the coordinator when options (e.g. scan interval) change
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

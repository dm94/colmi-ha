"""Binary sensor platform for the Colmi R09 Smart Ring."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAME, DOMAIN
from .coordinator import ColmiDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Colmi R09 binary sensor entities from a config entry."""
    coordinator: ColmiDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ColmiRingConnectionSensor(coordinator, entry)])


class ColmiRingConnectionSensor(CoordinatorEntity[ColmiDataUpdateCoordinator], BinarySensorEntity):
    """A binary sensor entity for tracking connection status."""

    _attr_has_entity_name = True
    _attr_name = "Connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self,
        coordinator: ColmiDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        address = entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{address}_connection"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=entry.data.get(CONF_NAME, f"Colmi R09 ({address})"),
            manufacturer="COLMI",
            model="R09",
        )

    @property
    def available(self) -> bool:
        """Return True so the entity is always available, showing 'Disconnected' rather than 'Unavailable'."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True if the last update from the coordinator was successful."""
        return self.coordinator.last_update_success

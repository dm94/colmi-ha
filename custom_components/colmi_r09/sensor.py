"""Sensor platform for the Colmi R09 Smart Ring.

Defines one SensorEntity per health/fitness metric, all reading from the
shared ColmiDataUpdateCoordinator.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ADDRESS,
    PERCENTAGE,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_NAME,
    DOMAIN,
    KEY_BATTERY,
    KEY_BLOOD_SUGAR,
    KEY_BP_DIASTOLIC,
    KEY_BP_SYSTOLIC,
    KEY_HEART_RATE,
    KEY_HRV,
    KEY_SPO2,
    KEY_STRESS,
    KEY_TEMPERATURE,
)
from .coordinator import ColmiDataUpdateCoordinator

# Custom unit strings not available as HA constants
UNIT_BPM = "bpm"
UNIT_MS = "ms"
UNIT_MG_DL = "mg/dL"


@dataclass(frozen=True)
class ColmiSensorEntityDescription(SensorEntityDescription):
    """Extended description that ties a sensor to a coordinator data key."""
    data_key: str = ""


SENSOR_DESCRIPTIONS: tuple[ColmiSensorEntityDescription, ...] = (
    ColmiSensorEntityDescription(
        key="battery",
        data_key=KEY_BATTERY,
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    ColmiSensorEntityDescription(
        key="heart_rate",
        data_key=KEY_HEART_RATE,
        name="Heart Rate",
        icon="mdi:heart-pulse",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UNIT_BPM,
    ),
    ColmiSensorEntityDescription(
        key="spo2",
        data_key=KEY_SPO2,
        name="Blood Oxygen (SpO2)",
        icon="mdi:blood-bag",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    ColmiSensorEntityDescription(
        key="blood_pressure_systolic",
        data_key=KEY_BP_SYSTOLIC,
        name="Blood Pressure Systolic",
        icon="mdi:heart-pulse",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="mmHg",
    ),
    ColmiSensorEntityDescription(
        key="blood_pressure_diastolic",
        data_key=KEY_BP_DIASTOLIC,
        name="Blood Pressure Diastolic",
        icon="mdi:heart-pulse",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="mmHg",
    ),
    ColmiSensorEntityDescription(
        key="temperature",
        data_key=KEY_TEMPERATURE,
        name="Body Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ColmiSensorEntityDescription(
        key="hrv",
        data_key=KEY_HRV,
        name="Heart Rate Variability (HRV)",
        icon="mdi:heart-flash",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UNIT_MS,
    ),
    ColmiSensorEntityDescription(
        key="stress",
        data_key=KEY_STRESS,
        name="Stress Level",
        icon="mdi:brain",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ColmiSensorEntityDescription(
        key="blood_sugar",
        data_key=KEY_BLOOD_SUGAR,
        name="Blood Sugar",
        icon="mdi:diabetes",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UNIT_MG_DL,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Colmi R09 sensor entities from a config entry."""
    coordinator: ColmiDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ColmiRingSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )


class ColmiRingSensor(CoordinatorEntity[ColmiDataUpdateCoordinator], SensorEntity):
    """A sensor entity for one Colmi R09 metric."""

    entity_description: ColmiSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ColmiDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ColmiSensorEntityDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        address = entry.data[CONF_ADDRESS]
        self._attr_unique_id = f"{address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=entry.data.get(CONF_NAME, f"Colmi R09 ({address})"),
            manufacturer="COLMI",
            model="R09",
        )

    @property
    def native_value(self) -> Any | None:
        """Return the current sensor value from coordinator data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.data_key)

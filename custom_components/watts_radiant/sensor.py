"""Floor / room temperature sensors for Watts Home."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WattsCoordinator
from .entity import thermostat_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up floor/room temperature sensors + Home/away sensor.

    The sensor is the explicit label for the Away mode switch
    in switch.py: the switch toggles the mode, the sensor states
    it as "Home" or "Away". Reusing the original sensor unique_id
    ("<location_id>_home_away") revives the 0.2.0 sensor entity
    in HA instead of creating yet another orphan.
    """
    coordinator: WattsCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for device_id in coordinator.data or {}:
        entities.append(WattsTempSensor(coordinator, device_id, "floor"))
        entities.append(WattsTempSensor(coordinator, device_id, "room"))
    for location_id in coordinator.locations or {}:
        entities.append(WattsHomeAwaySensor(coordinator, location_id))
    async_add_entities(entities)


class WattsHomeAwaySensor(CoordinatorEntity[WattsCoordinator], SensorEntity):
    """Home/Away state for one location (awayState 0 = Home).

    Name is "Home/away", not "Mode": "Mode" would be ambiguous
    next to thermostat Heat/Off mode and schedule mode, while
    "Home/away" matches the Watts term and its own values exactly.
    """

    def __init__(self, coordinator: WattsCoordinator, location_id: str) -> None:
        super().__init__(coordinator)
        self._location_id = location_id
        location = coordinator.locations[location_id]
        self._attr_unique_id = f"{location_id}_home_away"
        self._attr_name = f"{location.name} home/away"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, location_id)},
            "name": location.name,
            "manufacturer": "Watts",
            "model": "Location",
        }

    @property
    def native_value(self) -> str:
        return self.coordinator.locations[self._location_id].home_away


class WattsTempSensor(CoordinatorEntity[WattsCoordinator], SensorEntity):
    """A floor or room temperature sensor for one thermostat."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT

    def __init__(self, coordinator: WattsCoordinator, device_id: str, kind: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._kind = kind
        device = coordinator.data[device_id]
        self._attr_unique_id = f"{device_id}_{kind}_temperature"
        self._attr_name = f"{device.name} {kind} temperature"
        self._attr_device_info = thermostat_device_info(coordinator, device)

    @property
    def _device(self):
        return self.coordinator.data[self._device_id]

    @property
    def available(self) -> bool:
        return super().available and self._device.is_connected

    @property
    def native_value(self) -> float | None:
        device = self._device
        return device.floor_temp if self._kind == "floor" else device.room_temp

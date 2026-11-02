"""Schedule on/off switch per Watts Radiant thermostat."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
    """Set up schedule switches for each thermostat."""
    coordinator: WattsCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        WattsScheduleSwitch(coordinator, device_id)
        for device_id in coordinator.data or {}
    ]
    async_add_entities(entities)


class WattsScheduleSwitch(CoordinatorEntity[WattsCoordinator], SwitchEntity):
    """Toggle a thermostat's schedule (SchedEnable On/Off)."""

    def __init__(self, coordinator: WattsCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        device = coordinator.data[device_id]
        self._attr_unique_id = f"{device_id}_schedule"
        self._attr_name = f"{device.name} schedule"
        self._attr_device_info = thermostat_device_info(coordinator, device)

    @property
    def _device(self):
        return self.coordinator.data[self._device_id]

    @property
    def is_on(self) -> bool:
        return self._device.schedule_enabled

    @property
    def available(self) -> bool:
        return super().available and self._device.is_connected

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_schedule_enabled(self._device_id, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_schedule_enabled(self._device_id, False)

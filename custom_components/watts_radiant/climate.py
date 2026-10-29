"""Climate entities for Watts Radiant thermostats."""

from __future__ import annotations

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WattsCoordinator
from .entity import thermostat_device_info

_ACTION_MAP = {
    "heating": HVACAction.HEATING,
    "idle": HVACAction.IDLE,
    "off": HVACAction.OFF,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up climate entities from the coordinator."""
    coordinator: WattsCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        WattsClimate(coordinator, device_id)
        for device_id in coordinator.data or {}
    )


class WattsClimate(CoordinatorEntity[WattsCoordinator], ClimateEntity):
    """A Watts Sunstat thermostat, as a climate entity."""

    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    def __init__(self, coordinator: WattsCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        device = coordinator.data[device_id]
        self._attr_unique_id = device_id
        self._attr_name = device.name
        self._attr_device_info = thermostat_device_info(coordinator, device)

    @property
    def _device(self):
        return self.coordinator.data[self._device_id]

    @property
    def available(self) -> bool:
        return super().available and self._device.is_connected

    @property
    def current_temperature(self) -> float | None:
        # Floor sensor, as shown in the app ("Floor: XX°F").
        return self._device.current_temperature

    @property
    def target_temperature(self) -> float | None:
        return self._device.target_heat

    @property
    def preset_modes(self) -> list[str]:
        # Only meaningful with a schedule to return to. "Hold" is
        # listed only while a hold is active (as the current preset);
        # selecting it then is a no-op — a hold is created by
        # setting a temperature, not by selecting "Hold".
        if not self._device.schedule_enabled:
            return []
        return ["Schedule", "Hold"] if self._device.hold_active else ["Schedule"]

    @property
    def preset_mode(self) -> str | None:
        if not self._device.schedule_enabled:
            return None
        return "Hold" if self._device.hold_active else "Schedule"

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Schedule preset = cancel the HeatHold override."""
        if preset_mode == "Schedule" and self._device.hold_active:
            await self.coordinator.async_cancel_hold(self._device_id)
        # "Hold" (already holding) and any other case: no-op.

    @property
    def hvac_mode(self) -> str:
        return HVACMode.HEAT if self._device.hvac_mode == "heat" else HVACMode.OFF

    @property
    def hvac_action(self) -> str | None:
        return _ACTION_MAP.get(self._device.hvac_action)

    @property
    def min_temp(self) -> float:
        return self._device.target_min

    @property
    def max_temp(self) -> float:
        return self._device.target_max

    @property
    def target_temperature_step(self) -> float:
        return 1.0

    @property
    def extra_state_attributes(self) -> dict:
        device = self._device
        return {
            "floor_temperature": device.floor_temp,
            "room_temperature": device.room_temp,
            "target_sensor": device.target_sensor,
            "schedule_enabled": device.schedule_enabled,
            "schedule": device.schedule,
            "location": device.location_name,
            "state_op": device.state_op,
        }

    async def async_set_temperature(self, **kwargs) -> None:
        """Set temperature via PATCH /Device/{id} Settings.HeatHold."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.async_set_temperature(self._device_id, temperature)

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set HVAC mode via PATCH /Device/{id} Settings.Mode."""
        await self.coordinator.async_set_hvac_mode(self._device_id, hvac_mode)

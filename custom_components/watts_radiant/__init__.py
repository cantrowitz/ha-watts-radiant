"""Watts Radiant integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, PLATFORMS
from .coordinator import WattsCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Watts Home from a config entry."""
    coordinator = WattsCoordinator(hass, dict(entry.data))
    await coordinator.async_config_entry_first_refresh()
    # Register location parent devices FIRST, before any platform
    # registers a thermostat as a main device: a child conversion
    # is rejected if the device was already registered as a main
    # device during this setup. Same identifiers as the Home/Away
    # sensor's device, so this matches (not duplicates) it.
    registry = dr.async_get(hass)
    for location in coordinator.locations.values():
        parent = registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, location.location_id)},
            manufacturer="Watts",
            model="Location",
            name=location.name,
        )
        coordinator.location_device_ids[location.location_id] = parent.id
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok

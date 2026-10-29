"""Shared device-info helper for Watts Home entities.

Thermostats are child devices of their Watts location (HA Core
2026.9+ child-device model): the location is the parent device,
each thermostat is a child of it, so the location's device page
shows all its thermostats' entities. Identifiers are unchanged
from the pre-child version, so existing devices convert in place
and entity IDs are preserved.

ChildDeviceInfo carries no manufacturer/model — those belong to
the physical parent, per HA's model — so on HA versions without
ChildDeviceInfo (or if the parent device ID is somehow missing)
this falls back to the old standalone DeviceInfo dict, and the
integration still loads, just without nesting.
"""

from __future__ import annotations

from .const import DOMAIN

try:
    from homeassistant.helpers.device_registry import ChildDeviceInfo
except ImportError:  # HA < 2026.9
    ChildDeviceInfo = None  # type: ignore[assignment]


def thermostat_device_info(coordinator, device):
    """Device info for a thermostat: child of its location, if possible."""
    parent_id = getattr(coordinator, "location_device_ids", {}).get(
        device.location_id
    )
    if ChildDeviceInfo is not None and parent_id:
        return ChildDeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=device.name,
            parent_device_id=parent_id,
        )
    return {
        "identifiers": {(DOMAIN, device.device_id)},
        "name": device.name,
        "manufacturer": "SunTouch",
        "model": device.model_number,
    }

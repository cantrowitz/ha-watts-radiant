"""Pure data models for Watts Radiant — no Home Assistant imports.

This module is deliberately testable without HA installed, so the
mapping from the Watts API (and from Adam's app screenshot) to HA
concepts can be verified offline with synthetic fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WattsLocation:
    """One Watts location, for grouping and Home/Away."""

    location_id: str
    name: str
    away_state: int = 0

    @property
    def home_away(self) -> str:
        """awayState 0 is Home (Adam's reading, Oct 28, 2026)."""
        return "Home" if self.away_state == 0 else "Away"


def parse_location(entry: dict) -> WattsLocation:
    return WattsLocation(
        location_id=entry.get("locationId", ""),
        name=entry.get("name", ""),
        away_state=int(entry.get("awayState", 0) or 0),
    )


@dataclass
class WattsDevice:
    """One thermostat, as returned by Location/{id}/Devices."""

    device_id: str
    name: str
    location_id: str
    location_name: str
    model_number: str = "SunstatGen4"
    is_connected: bool = True
    # Temperatures in Fahrenheit, as the API reports them (TempUnits F).
    floor_temp: float | None = None
    room_temp: float | None = None
    # Mode: "Off" or "Heat" (Mode.Val). State.Op: "Off", "Heat", ...
    mode: str = "Heat"
    state_op: str = "Off"
    target_heat: float | None = None
    target_min: float = 40.0
    target_max: float = 85.0
    target_sensor: str = "Floor"
    schedule_enabled: bool = True
    schedule: dict = field(default_factory=dict)
    # Target.Hold: 0 = following schedule, non-zero = temperature
    # override (HeatHold) is active. Parsed, not invented.
    hold: int = 0
    raw: dict = field(default_factory=dict)

    @property
    def current_temperature(self) -> float | None:
        """Current temperature shown in the app: the floor sensor.

        The app's device cards lead with "Floor: XX°F" (Adam's
        screenshot: main bathroom Floor 76°F, second bathroom
        Floor 80°F), and Target.Sensor is "Floor" on both devices.
        The room sensor is exposed separately, not as the primary.
        """
        if self.target_sensor == "Floor":
            return self.floor_temp
        return self.room_temp

    @property
    def hold_active(self) -> bool:
        """True when a HeatHold override is active (not following schedule)."""
        return bool(self.hold)

    @property
    def hvac_mode(self) -> str:
        """HA hvac mode: "off" or "heat"."""
        return "heat" if self.mode == "Heat" else "off"

    @property
    def hvac_action(self) -> str | None:
        """HA hvac action: Op Heat AND current below target.

        Paired on/off captures Oct 29, 2026 (main bathroom,
        37 seconds apart) prove Op alone cannot distinguish:
        Op was "Heat", Mode.Active 1, Sub "None", sensors,
        schedule and energy all identical in both — the only
        difference was Target.Heat 78 (on, floor 77 < target)
        vs 76 (off, floor 77 > target). Heating therefore
        requires both State.Op "Heat" and current temperature
        (following the target sensor) below the target;
        otherwise the action is idle, and the HA card should
        not glow orange.
        """
        if self.hvac_mode == "off":
            return "off"
        current = self.current_temperature
        target = self.target_heat
        if self.state_op == "Heat":
            if current is None or target is None:
                return "heating"
            return "heating" if current < target else "idle"
        return "idle"


def parse_device(entry: dict, location_id: str | None = None, location_name: str | None = None) -> WattsDevice:
    """Parse one Location/Devices body entry into a WattsDevice.

    The caller (coordinator) passes the location from the endpoint
    URL, which is authoritative — the device entry itself may or
    may not carry a location object, so don't rely on it for grouping.
    """
    data = entry.get("data") or {}
    sensors = data.get("Sensors") or {}
    room = sensors.get("Room") or {}
    floor = sensors.get("Floor") or {}
    state = data.get("State") or {}
    mode = data.get("Mode") or {}
    target = data.get("Target") or {}
    sched = data.get("SchedEnable") or {}
    loc = entry.get("location") or {}
    return WattsDevice(
        device_id=entry.get("deviceId", ""),
        name=entry.get("name", ""),
        location_id=location_id if location_id is not None else loc.get("locationId", ""),
        location_name=location_name if location_name is not None else loc.get("name", ""),
        model_number=entry.get("modelNumber", "SunstatGen4"),
        is_connected=bool(entry.get("isConnected", True)),
        floor_temp=_as_float(floor.get("Val")),
        room_temp=_as_float(room.get("Val")),
        mode=mode.get("Val", "Heat"),
        state_op=state.get("Op", "Off"),
        target_heat=_as_float(target.get("Heat")),
        target_min=_as_float(target.get("Min"), 40.0),
        target_max=_as_float(target.get("Max"), 85.0),
        target_sensor=target.get("Sensor", "Floor"),
        hold=int(target.get("Hold") or 0),
        schedule_enabled=(sched.get("Val") == "On"),
        schedule=data.get("Schedule") or {},
        raw=entry,
    )


def _as_float(value: object, default: float | None = None) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default

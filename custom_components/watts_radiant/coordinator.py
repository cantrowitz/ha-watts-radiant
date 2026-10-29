"""Data coordinator for Watts Home."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import WattsApiClient, WattsAuthClient, WattsInvalidAuth
from .const import DOMAIN
from .models import WattsDevice, WattsLocation, parse_device, parse_location


class WattsCoordinator(DataUpdateCoordinator[dict[str, WattsDevice]]):
    """Poll Watts locations/devices, refreshing tokens as needed."""

    def __init__(self, hass: HomeAssistant, entry_data: dict) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=DOMAIN,
            update_interval=timedelta(seconds=60),
        )
        self._entry_data = entry_data
        self._tokens = None
        self.location_name = "801"
        self.locations: dict[str, WattsLocation] = {}
        # HA device-registry IDs of location parent devices, filled
        # in by async_setup_entry before platforms load.
        self.location_device_ids: dict[str, str] = {}

    @property
    def tokens(self):
        return self._tokens

    async def _ensure_tokens(self, session):
        from .api import Tokens

        if self._tokens is None:
            self._tokens = Tokens.from_dict(self._entry_data["tokens"])
        if self._tokens.expired:
            auth = WattsAuthClient(session)
            self._tokens = await auth.refresh(self._tokens.refresh_token)
            # Persist refreshed tokens back to the config entry.
            self._entry_data["tokens"] = self._tokens.to_dict()

    async def async_set_hvac_mode(self, device_id: str, hvac_mode: str) -> None:
        """Set a thermostat's mode via the API, then re-poll."""
        mode = "Off" if hvac_mode == "off" else "Heat"
        session = async_get_clientsession(self.hass)
        await self._ensure_tokens(session)
        api = WattsApiClient(session, self._tokens)
        try:
            await api.set_device_mode(device_id, mode)
        except WattsInvalidAuth:
            auth = WattsAuthClient(session)
            self._tokens = await auth.refresh(self._tokens.refresh_token)
            self._entry_data["tokens"] = self._tokens.to_dict()
            api = WattsApiClient(session, self._tokens)
            await api.set_device_mode(device_id, mode)
        await self.async_refresh()

    async def async_set_temperature(self, device_id: str, temperature: float) -> None:
        """Set a thermostat's heat target via the API, then re-poll."""
        device = self.data.get(device_id) if self.data else None
        schedule_enabled = bool(device.schedule_enabled) if device else True
        session = async_get_clientsession(self.hass)
        await self._ensure_tokens(session)
        api = WattsApiClient(session, self._tokens)
        try:
            await api.set_device_temperature(device_id, temperature, schedule_enabled)
        except WattsInvalidAuth:
            auth = WattsAuthClient(session)
            self._tokens = await auth.refresh(self._tokens.refresh_token)
            self._entry_data["tokens"] = self._tokens.to_dict()
            api = WattsApiClient(session, self._tokens)
            await api.set_device_temperature(device_id, temperature, schedule_enabled)
        await self.async_refresh()

    async def async_cancel_hold(self, device_id: str) -> None:
        """Cancel a thermostat's temperature override, then re-poll."""
        session = async_get_clientsession(self.hass)
        await self._ensure_tokens(session)
        api = WattsApiClient(session, self._tokens)
        try:
            await api.cancel_device_hold(device_id)
        except WattsInvalidAuth:
            auth = WattsAuthClient(session)
            self._tokens = await auth.refresh(self._tokens.refresh_token)
            self._entry_data["tokens"] = self._tokens.to_dict()
            api = WattsApiClient(session, self._tokens)
            await api.cancel_device_hold(device_id)
        await self.async_refresh()

    async def async_set_schedule_enabled(self, device_id: str, enabled: bool) -> None:
        """Toggle a thermostat's schedule via the API, then re-poll."""
        session = async_get_clientsession(self.hass)
        await self._ensure_tokens(session)
        api = WattsApiClient(session, self._tokens)
        try:
            await api.set_schedule_enabled(device_id, enabled)
        except WattsInvalidAuth:
            auth = WattsAuthClient(session)
            self._tokens = await auth.refresh(self._tokens.refresh_token)
            self._entry_data["tokens"] = self._tokens.to_dict()
            api = WattsApiClient(session, self._tokens)
            await api.set_schedule_enabled(device_id, enabled)
        await self.async_refresh()

    async def async_set_away(self, location_id: str, away: bool) -> None:
        """Toggle a location's Home/Away state via the API, then re-poll."""
        session = async_get_clientsession(self.hass)
        await self._ensure_tokens(session)
        api = WattsApiClient(session, self._tokens)
        try:
            await api.set_location_away_state(location_id, away)
        except WattsInvalidAuth:
            auth = WattsAuthClient(session)
            self._tokens = await auth.refresh(self._tokens.refresh_token)
            self._entry_data["tokens"] = self._tokens.to_dict()
            api = WattsApiClient(session, self._tokens)
            await api.set_location_away_state(location_id, away)
        await self.async_refresh()

    async def _async_update_data(self) -> dict[str, WattsDevice]:
        session = async_get_clientsession(self.hass)
        try:
            await self._ensure_tokens(session)
            api = WattsApiClient(session, self._tokens)
            try:
                locations = await api.get_locations()
            except WattsInvalidAuth:
                # Token may have expired between the check and the
                # call; refresh once and retry.
                auth = WattsAuthClient(session)
                self._tokens = await auth.refresh(self._tokens.refresh_token)
                self._entry_data["tokens"] = self._tokens.to_dict()
                api = WattsApiClient(session, self._tokens)
                locations = await api.get_locations()

            devices: dict[str, WattsDevice] = {}
            self.locations = {}
            for loc in locations:
                location_id = loc.get("locationId")
                if not location_id:
                    continue
                parsed_loc = parse_location(loc)
                self.locations[location_id] = parsed_loc
                if loc.get("isDefault"):
                    self.location_name = loc.get("name", self.location_name)
                for entry in await api.get_location_devices(location_id):
                    device = parse_device(
                        entry,
                        location_id=location_id,
                        location_name=parsed_loc.name,
                    )
                    devices[device.device_id] = device
            return devices
        except WattsInvalidAuth as err:
            raise UpdateFailed(f"Watts authentication failed: {err}") from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Watts update failed: {err}") from err

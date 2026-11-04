"""Tests for the Nov 2, 2026 HACS review fixes (frenck, PR #12915).

1. Refreshed tokens must be persisted to the config entry, not just
   a copy of its data.
2. A rejected refresh token must raise ConfigEntryAuthFailed (so HA
   starts reauth) and the config flow must offer a reauth step.
3. The Away Mode switch and its unverified write call must be gone;
   the read-only Home/Away sensor stays.

The real homeassistant package is not installed here, so the HA
surface these modules touch is faked with small stand-ins that
mirror the real API names (same approach as the Tempur suite's
stubs). Only behavior is asserted, never stub internals.
"""

import asyncio
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace

COMP = Path(__file__).resolve().parents[1] / "custom_components" / "watts_radiant"

_pkg = types.ModuleType("watts_radiant")
_pkg.__path__ = [str(COMP)]
sys.modules["watts_radiant"] = _pkg


def _module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


class _HomeAssistant:
    pass


class _ConfigEntryAuthFailed(Exception):
    pass


class _UpdateFailed(Exception):
    pass


class _ConfigEntry:
    def __init__(self, entry_id, data, unique_id=None):
        self.entry_id = entry_id
        self.data = data
        self.unique_id = unique_id


class _ConfigFlow:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()
        if "domain" in kwargs:
            cls.domain = kwargs["domain"]

    def __init__(self):
        self.hass = None
        self.handler = None
        self.context = {}

    async def async_set_unique_id(self, unique_id):
        self._unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        pass

    def _abort_if_unique_id_mismatch(self, *, reason):
        # Mirror of real HA: raises when the flow's unique id differs
        # from the entry being re-authenticated.
        if getattr(self, "_unique_id", None) != self._reauth_entry.unique_id:
            raise _AbortFlow(reason)

    def async_show_form(self, *, step_id, data_schema, errors):
        return {"type": "form", "step_id": step_id, "errors": errors}

    def async_create_entry(self, *, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    def async_abort(self, *, reason):
        return {"type": "abort", "reason": reason}

    def async_update_reload_and_abort(self, entry, *, data_updates):
        return {
            "type": "abort",
            "reason": "reauth_successful",
            "entry": entry,
            "data_updates": data_updates,
        }


class _AbortFlow(Exception):
    """Stand-in for HA's AbortFlow, carrying the abort reason."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class _DataUpdateCoordinator:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, *, logger, name, update_interval):
        self.hass = hass
        self.data = None

    async def async_refresh(self):
        self.data = await self._async_update_data()


class _CoordinatorEntity:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator):
        self.coordinator = coordinator


class _SwitchEntity:
    pass


class _ChildDeviceInfo:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _async_get_clientsession(hass):
    # Real HA's async_get_clientsession is a plain function despite
    # the name; it returns the shared session synchronously.
    return object()


ha = _module("homeassistant")
ha_config_entries = _module(
    "homeassistant.config_entries",
    ConfigFlow=_ConfigFlow,
    ConfigFlowResult=dict,
    ConfigEntry=_ConfigEntry,
)
ha.config_entries = ha_config_entries
_module("homeassistant.core", HomeAssistant=_HomeAssistant)
_module("homeassistant.exceptions", ConfigEntryAuthFailed=_ConfigEntryAuthFailed)
_module(
    "homeassistant.const", CONF_USERNAME="username", CONF_PASSWORD="password"
)
_module("homeassistant.helpers")
_module(
    "homeassistant.helpers.aiohttp_client",
    async_get_clientsession=_async_get_clientsession,
)
_module(
    "homeassistant.helpers.update_coordinator",
    DataUpdateCoordinator=_DataUpdateCoordinator,
    UpdateFailed=_UpdateFailed,
    CoordinatorEntity=_CoordinatorEntity,
)
_module(
    "homeassistant.helpers.entity_platform", AddEntitiesCallback=object
)
_module(
    "homeassistant.helpers.device_registry", ChildDeviceInfo=_ChildDeviceInfo
)
_module("homeassistant.components")
_module("homeassistant.components.switch", SwitchEntity=_SwitchEntity)

from watts_radiant.api import (
    Tokens,
    WattsApiClient,
    WattsAuthClient,
    WattsAuthError,
    WattsInvalidAuth,
)
from watts_radiant.config_flow import WattsRadiantConfigFlow
from watts_radiant.coordinator import WattsCoordinator
from watts_radiant import switch as switch_mod
from watts_radiant import coordinator as coord_mod
from watts_radiant import config_flow as flow_mod
from watts_radiant import api as api_mod


def _old_tokens():
    return {
        "access_token": "old-access",
        "refresh_token": "old-refresh",
        "expires_at": time.time() - 100,  # expired: forces a refresh
    }


def _new_tokens():
    return Tokens(
        access_token="new-access",
        refresh_token="new-refresh",
        expires_at=time.time() + 3600,
    )


class _FakeConfigEntries:
    def __init__(self):
        self.entries = {}
        self.updated = []

    def async_update_entry(self, entry, *, data):
        entry.data = data
        self.updated.append((entry, data))

    def async_get_entry(self, entry_id):
        return self.entries.get(entry_id)

    def async_entries(self, domain):
        return list(self.entries.values())


class _FakeHass:
    def __init__(self):
        self.config_entries = _FakeConfigEntries()
        self.data = {}


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_refresh_persists_tokens_to_config_entry(monkeypatch):
    """A token refresh must reach HA storage, not just an in-memory copy."""
    hass = _FakeHass()
    entry = _ConfigEntry(
        "e1",
        {"username": "a@example.com", "tokens": _old_tokens()},
        unique_id="a@example.com",
    )
    hass.config_entries.entries = {"e1": entry}

    class FakeAuth:
        def __init__(self, session):
            pass

        async def refresh(self, refresh_token):
            assert refresh_token == "old-refresh"
            return _new_tokens()

    monkeypatch.setattr(coord_mod, "WattsAuthClient", FakeAuth)
    coord = WattsCoordinator(hass, entry)
    _run(coord._ensure_tokens(object()))

    assert entry.data["tokens"]["refresh_token"] == "new-refresh"
    assert hass.config_entries.updated
    updated_entry, updated_data = hass.config_entries.updated[-1]
    assert updated_entry is entry
    assert updated_data["tokens"]["refresh_token"] == "new-refresh"
    # Username and everything else in the entry must survive the update.
    assert updated_data["username"] == "a@example.com"


def test_rejected_refresh_raises_config_entry_auth_failed(monkeypatch):
    """Poll auth failure must trigger reauth, not a plain update failure."""
    hass = _FakeHass()
    entry = _ConfigEntry(
        "e1",
        {"username": "a@example.com", "tokens": _old_tokens()},
        unique_id="a@example.com",
    )
    hass.config_entries.entries = {"e1": entry}

    class FailingAuth:
        def __init__(self, session):
            pass

        async def refresh(self, refresh_token):
            raise WattsInvalidAuth("refresh rejected")

    monkeypatch.setattr(coord_mod, "WattsAuthClient", FailingAuth)
    coord = WattsCoordinator(hass, entry)
    try:
        _run(coord._async_update_data())
    except _ConfigEntryAuthFailed:
        pass
    else:
        raise AssertionError("expected ConfigEntryAuthFailed")


def test_poll_error_other_than_auth_stays_update_failed(monkeypatch):
    """Non-auth poll failures must stay UpdateFailed, not trigger reauth."""
    hass = _FakeHass()
    entry = _ConfigEntry(
        "e1",
        {"username": "a@example.com", "tokens": _old_tokens()},
        unique_id="a@example.com",
    )
    hass.config_entries.entries = {"e1": entry}

    class FakeAuth:
        def __init__(self, session):
            pass

        async def refresh(self, refresh_token):
            return _new_tokens()

    class FailingApi:
        def __init__(self, session, tokens):
            pass

        async def get_locations(self):
            raise RuntimeError("network down")

    monkeypatch.setattr(coord_mod, "WattsAuthClient", FakeAuth)
    monkeypatch.setattr(coord_mod, "WattsApiClient", FailingApi)
    coord = WattsCoordinator(hass, entry)
    try:
        _run(coord._async_update_data())
    except _UpdateFailed:
        pass
    else:
        raise AssertionError("expected UpdateFailed")


def _reauth_flow(hass, entry):
    flow = WattsRadiantConfigFlow()
    flow.hass = hass
    flow.handler = entry.entry_id
    flow.context = {"entry_id": entry.entry_id}
    return flow


def test_reauth_confirm_updates_tokens(monkeypatch):
    hass = _FakeHass()
    entry = _ConfigEntry(
        "e1",
        {"username": "a@example.com", "tokens": _old_tokens()},
        unique_id="a@example.com",
    )
    hass.config_entries.entries = {"e1": entry}

    class FakeAuth:
        def __init__(self, session):
            pass

        async def authenticate(self, username, password):
            assert username == "a@example.com" and password == "pw"
            return _new_tokens()

    monkeypatch.setattr(flow_mod, "WattsAuthClient", FakeAuth)
    flow = _reauth_flow(hass, entry)
    form = _run(flow.async_step_reauth({"username": "a@example.com"}))
    assert form["type"] == "form" and form["step_id"] == "reauth_confirm"
    result = _run(
        flow.async_step_reauth_confirm(
            {"username": "a@example.com", "password": "pw"}
        )
    )
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert result["entry"] is entry
    assert result["data_updates"]["tokens"]["refresh_token"] == "new-refresh"


def test_reauth_confirm_invalid_auth_shows_error(monkeypatch):
    hass = _FakeHass()
    entry = _ConfigEntry(
        "e1",
        {"username": "a@example.com", "tokens": _old_tokens()},
        unique_id="a@example.com",
    )
    hass.config_entries.entries = {"e1": entry}

    class FailingAuth:
        def __init__(self, session):
            pass

        async def authenticate(self, username, password):
            raise WattsInvalidAuth("bad password")

    monkeypatch.setattr(flow_mod, "WattsAuthClient", FailingAuth)
    flow = _reauth_flow(hass, entry)
    _run(flow.async_step_reauth({"username": "a@example.com"}))
    result = _run(
        flow.async_step_reauth_confirm(
            {"username": "a@example.com", "password": "wrong"}
        )
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_auth"}


def test_reauth_confirm_refuses_different_account():
    """Reauth with another account's email aborts as wrong_account."""
    hass = _FakeHass()
    entry = _ConfigEntry(
        "e1",
        {"username": "a@example.com", "tokens": _old_tokens()},
        unique_id="a@example.com",
    )
    hass.config_entries.entries = {"e1": entry}
    flow = _reauth_flow(hass, entry)
    _run(flow.async_step_reauth({"username": "a@example.com"}))
    try:
        _run(
            flow.async_step_reauth_confirm(
                {"username": "b@example.com", "password": "pw"}
            )
        )
    except _AbortFlow as err:
        assert err.reason == "wrong_account"
    else:
        raise AssertionError("expected wrong_account abort")


def _refresh_with_status(monkeypatch, status_code, json_raises=False):
    """Run WattsAuthClient.refresh against a fake token endpoint."""

    class FakeResp:
        def __init__(self):
            self.status_code = status_code

        def json(self):
            if json_raises:
                raise ValueError("not JSON")
            return {}

    class FakeCurlSession:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return FakeResp()

    monkeypatch.setattr(api_mod, "CurlSession", FakeCurlSession)
    return _run(WattsAuthClient().refresh("some-refresh-token"))


def test_refresh_rejected_grant_is_invalid_auth(monkeypatch):
    """Only 400/401 from the token endpoint mean the grant is rejected."""
    for status_code in (400, 401):
        try:
            _refresh_with_status(monkeypatch, status_code)
        except WattsInvalidAuth:
            pass
        else:
            raise AssertionError(f"expected WattsInvalidAuth for {status_code}")


def test_refresh_transient_error_is_not_invalid_auth(monkeypatch):
    """5xx/429 from the token endpoint must not force re-authentication."""
    for status_code in (429, 500, 502, 503):
        try:
            _refresh_with_status(monkeypatch, status_code)
        except WattsInvalidAuth:
            raise AssertionError(
                f"transient {status_code} must not raise WattsInvalidAuth"
            )
        except WattsAuthError:
            pass
        else:
            raise AssertionError(f"expected WattsAuthError for {status_code}")


def test_refresh_non_json_error_page_is_auth_error(monkeypatch):
    """Status is checked before json(): a non-JSON error page is WattsAuthError."""
    try:
        _refresh_with_status(monkeypatch, 500, json_raises=True)
    except WattsInvalidAuth:
        raise AssertionError("non-JSON 500 must not raise WattsInvalidAuth")
    except WattsAuthError:
        pass
    else:
        raise AssertionError("expected WattsAuthError")


def test_transient_refresh_failure_is_update_failed_not_reauth(monkeypatch):
    """A transient refresh failure retries next poll instead of reauth."""
    hass = _FakeHass()
    entry = _ConfigEntry(
        "e1",
        {"username": "a@example.com", "tokens": _old_tokens()},
        unique_id="a@example.com",
    )
    hass.config_entries.entries = {"e1": entry}

    class TransientFailAuth:
        def __init__(self, session):
            pass

        async def refresh(self, refresh_token):
            raise WattsAuthError("token endpoint 500")

    monkeypatch.setattr(coord_mod, "WattsAuthClient", TransientFailAuth)
    coord = WattsCoordinator(hass, entry)
    try:
        _run(coord._async_update_data())
    except _ConfigEntryAuthFailed:
        raise AssertionError("transient failure must not raise ConfigEntryAuthFailed")
    except _UpdateFailed:
        pass
    else:
        raise AssertionError("expected UpdateFailed")


def test_switch_setup_creates_no_away_switch():
    """Only schedule switches remain; the Away Mode switch is gone."""
    hass = _FakeHass()
    device = SimpleNamespace(
        device_id="dev1",
        name="main bathroom",
        model_number="SunstatGen4",
        location_id="loc1",
    )
    coordinator = SimpleNamespace(
        data={"dev1": device},
        locations={"loc1": SimpleNamespace(name="801", location_id="loc1")},
        location_device_ids={},
    )
    hass.data = {"watts_radiant": {"e1": coordinator}}
    added = []
    _run(
        switch_mod.async_setup_entry(
            hass,
            SimpleNamespace(entry_id="e1"),
            added.extend,
        )
    )
    assert len(added) == 1
    assert type(added[0]).__name__ == "WattsScheduleSwitch"
    assert not hasattr(switch_mod, "WattsAwaySwitch")


def test_away_write_call_is_gone():
    assert not hasattr(WattsApiClient, "set_location_away_state")
    import watts_radiant.api as api_mod

    assert not hasattr(api_mod, "away_state_payload")

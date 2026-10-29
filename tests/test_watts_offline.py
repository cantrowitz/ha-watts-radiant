"""Offline tests for Watts mapping — synthetic fixtures only.

No real account IDs, tokens, or credentials appear here. The fixture
shapes mirror Adam's captured Location/Devices responses and his app
screenshot: main bathroom floor 76°F / target 80°F / heating, second
bathroom floor 80°F / target 65°F / mode Heat but not heating.
"""

import sys
import types
from pathlib import Path

# Load watts_radiant.api/models WITHOUT executing the HA-dependent
# package __init__ (which imports homeassistant, not installed here).
# Register a bare package with __path__ so submodule imports work.
_pkg_path = str(Path(__file__).resolve().parents[1] / "custom_components" / "watts_radiant")
_pkg = types.ModuleType("watts_radiant")
_pkg.__path__ = [_pkg_path]
sys.modules["watts_radiant"] = _pkg

from watts_radiant.api import (
    build_authorize_url,
    build_confirmed_url,
    extract_b2c_page_params,
    extract_code_from_confirmed_html,
    extract_code_from_redirect,
    generate_pkce,
)
from watts_radiant.models import parse_device, parse_location


def _fixture(name, floor, room, op, target):
    return {
        "deviceId": f"fake-{name}",
        "name": name,
        "modelNumber": "SunstatGen4",
        "isConnected": True,
        "location": {"locationId": "fake-location", "name": "801"},
        "data": {
            "Sensors": {
                "Room": {"Val": room, "Status": "Okay"},
                "Floor": {"Val": floor, "Status": "Okay"},
            },
            "State": {"Op": op, "Sub": "None"},
            "Mode": {"Active": 1, "Val": "Heat", "Enum": ["Off", "Heat"]},
            "Target": {
                "Active": 1,
                "Sensor": "Floor",
                "Hold": 0,
                "Heat": target,
                "Min": 40,
                "Max": 85,
                "Steps": 1,
            },
            "SchedEnable": {"Active": 1, "Val": "On"},
            "TempUnits": {"Val": "F"},
        },
    }


def test_main_bathroom_is_heating_with_floor_as_current():
    device = parse_device(_fixture("main bathroom", 76, 84, "Heat", 80))
    assert device.current_temperature == 76
    assert device.room_temp == 84
    assert device.hvac_mode == "heat"
    assert device.hvac_action == "heating"
    assert device.target_heat == 80


def test_second_bathroom_is_idle_when_floor_above_target():
    device = parse_device(_fixture("second bathroom", 80, 78, "Off", 65))
    assert device.current_temperature == 80
    assert device.hvac_mode == "heat"
    # Mode is Heat, but State.Op is Off: the app shows "Heat | 65°F",
    # not "Heating up" — so HA action is idle, not heating.
    assert device.hvac_action == "idle"
    assert device.target_heat == 65


def test_pkce_and_authorize_url():
    pkce = generate_pkce()
    assert len(pkce.verifier) >= 43
    assert pkce.challenge != pkce.verifier
    url = build_authorize_url(pkce, "test-state")
    assert "login.watts.io/tfp/" in url
    assert "response_type=code" in url
    assert "code_challenge_method=S256" in url
    assert "msal" in url and "%3A%2F%2Fauth" in url


def test_extract_b2c_page_params_and_code():
    page = (
        'var SETTINGS = {"csrf": "fake-csrf-123", '
        '"transId": "StateProperties=fake-trans-456"};'
    )
    csrf, trans = extract_b2c_page_params(page)
    assert csrf == "fake-csrf-123"
    assert trans == "StateProperties=fake-trans-456"
    code = extract_code_from_redirect(
        "msal00000000-0000-0000-0000-000000000000://auth?code=fake-code&state=x"
    )
    assert code == "fake-code"


def test_confirmed_url_has_no_tfp_and_parses_object_moved():
    url = build_confirmed_url("fake-csrf", "StateProperties=fake-trans")
    assert "/tfp/" not in url
    assert "/api/CombinedSigninAndSignup/confirmed" in url
    assert "rememberMe=false" in url
    # Shape of Adam's capture: href is the whole msal URL, URL-encoded.
    html = (
        '<html><body><h2>Object moved to '
        '<a href="msal00000000-0000-0000-0000-000000000000%3a%2f%2fauth%2f'
        "%3fstate%3dabc%26code%3dfake-code-123\">here</a>.</h2></body></html>"
    )
    assert extract_code_from_confirmed_html(html) == "fake-code-123"


def test_home_away():
    assert parse_location({"locationId": "x", "name": "801", "awayState": 0}).home_away == "Home"
    assert parse_location({"locationId": "x", "name": "801", "awayState": 1}).home_away == "Away"


def test_parse_device_location_override_wins():
    # Coordinator passes the endpoint's location, which must win
    # over a missing/wrong location object in the device entry —
    # this is what the child-device parent link relies on.
    entry = _fixture("main bathroom", 76, 84, "Heat", 80)
    entry.pop("location", None)
    device = parse_device(entry, location_id="loc-123", location_name="801")
    assert device.location_id == "loc-123"
    assert device.location_name == "801"


def test_mode_off_parses_to_null_target():
    entry = _fixture("main bathroom", 77, 81, "Heat", 65)
    entry["data"]["Mode"]["Val"] = "Off"
    entry["data"]["Target"]["Active"] = 0
    entry["data"]["Target"]["Heat"] = None
    device = parse_device(entry)
    assert device.hvac_mode == "off"
    assert device.hvac_action == "off"
    assert device.target_heat is None


def test_temp_settings_payload():
    from watts_radiant.api import temp_settings_payload

    assert temp_settings_payload(66, True) == {"Settings": {"HeatHold": 66}}
    assert temp_settings_payload(72, False) == {"Settings": {"Heat": 72}}


def test_hold_parsing():
    entry = _fixture("main bathroom", 77, 81, "Heat", 65)
    assert parse_device(entry).hold_active is False
    entry["data"]["Target"]["Hold"] = 1
    assert parse_device(entry).hold_active is True


def test_schedule_parsing_and_heat_payload():
    from watts_radiant.api import temp_settings_payload

    entry = _fixture("main bathroom", 77, 81, "Heat", 79)
    entry["data"]["Schedule"] = {"Grp1": {"S": {"T": "23:50", "H": 79}}}
    device = parse_device(entry)
    assert device.schedule_enabled is True
    assert device.schedule["Grp1"]["S"]["H"] == 79
    # Schedule-off temperature payload, now verified (Heat 84).
    assert temp_settings_payload(84, False) == {"Settings": {"Heat": 84}}


def test_away_state_payload():
    from watts_radiant.api import away_state_payload

    assert away_state_payload(True) == {"awayState": 1}
    assert away_state_payload(False) == {"awayState": 0}


def test_heating_requires_op_and_current_below_target():
    # Paired on/off captures Oct 29, 2026: Op Heat in both,
    # floor 77, target 78 => heating, target 76 => idle.
    # Op alone cannot distinguish; the temp comparison can.
    entry = _fixture("main bathroom", 77, 84, "Heat", 78)
    assert parse_device(entry).hvac_action == "heating"
    entry = _fixture("main bathroom", 77, 84, "Heat", 76)
    assert parse_device(entry).hvac_action == "idle"
    entry = _fixture("second bathroom", 80, 78, "Off", 65)
    assert parse_device(entry).hvac_action == "idle"

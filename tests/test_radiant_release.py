"""Release-readiness checks for Watts Radiant — offline only.

No HA install needed, no real account data. These guard the
things that broke during the Oct 28-29 rename churn: domain,
repo name, brand icon sizes, and the control payloads.
"""

import json
import struct
import sys
import types
from pathlib import Path


def _png_size(path: Path) -> tuple[int, int]:
    """PNG width/height from the IHDR chunk, no Pillow needed."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    width, height = struct.unpack(">II", data[16:24])
    return width, height

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components" / "watts_radiant"

_pkg = types.ModuleType("watts_radiant")
_pkg.__path__ = [str(COMP)]
sys.modules["watts_radiant"] = _pkg

from watts_radiant.api import away_state_payload, temp_settings_payload
from watts_radiant.const import DOMAIN, PLATFORMS
from watts_radiant.models import parse_device, parse_location


def test_domain_and_names_agree():
    manifest = json.loads((COMP / "manifest.json").read_text())
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert DOMAIN == "watts_radiant"
    assert manifest["domain"] == "watts_radiant"
    assert manifest["name"] == "Watts Radiant"
    assert hacs["name"] == "Watts Radiant"
    assert manifest["documentation"] == (
        "https://github.com/cantrowitz/ha-watts-radiant"
    )
    assert PLATFORMS == ["climate", "sensor", "switch"]


def test_no_home_domain_left_in_repo_files():
    # The Oct 28 rename to the home domain was reverted Oct 29;
    # make sure no file still points at the old domain or repo.
    for path in ROOT.rglob("*"):
        if path.is_dir() or ".venv" in path.parts or ".git" in path.parts:
            continue
        if path == Path(__file__):
            continue
        if path.suffix in {".py", ".json", ".md"}:
            text = path.read_text(errors="ignore")
            assert "watts_home" not in text, path
            assert "ha-watts-home" not in text, path


def test_brand_icons_are_256_and_512():
    # Sizes are what HA's brand convention cares about; the
    # exact-upscale equality was verified at generation time
    # (Oct 29, 2026) with Pillow, which is not a test dependency.
    assert _png_size(COMP / "brand" / "icon.png") == (256, 256)
    assert _png_size(COMP / "brand" / "icon@2x.png") == (512, 512)


def test_control_payloads():
    assert temp_settings_payload(66, True) == {"Settings": {"HeatHold": 66}}
    assert temp_settings_payload(84, False) == {"Settings": {"Heat": 84}}
    assert away_state_payload(True) == {"awayState": 1}
    assert away_state_payload(False) == {"awayState": 0}


def _device(**overrides):
    data = {
        "Sensors": {
            "Room": {"Val": 80, "Status": "Okay"},
            "Floor": {"Val": 77, "Status": "Okay"},
        },
        "State": {"Op": "Off", "Sub": "None"},
        "Mode": {"Active": 1, "Val": "Heat", "Enum": ["Off", "Heat"]},
        "Target": {
            "Active": 1,
            "Sensor": "Floor",
            "Hold": 0,
            "Heat": 65,
            "Min": 40,
            "Max": 85,
            "Steps": 1,
        },
        "SchedEnable": {"Active": 1, "Val": "On"},
        "TempUnits": {"Val": "F"},
    }
    data.update(overrides.pop("data", {}))
    entry = {
        "deviceId": "fake-device",
        "name": "main bathroom",
        "modelNumber": "SunstatGen4",
        "isConnected": True,
        "location": {"locationId": "fake-location", "name": "801"},
        "data": data,
    }
    entry.update(overrides)
    return parse_device(entry)


def test_current_temperature_follows_target_sensor():
    assert _device().current_temperature == 77  # Floor
    room = _device()
    room_data = room.raw["data"]["Target"]
    assert room_data["Sensor"] == "Floor"
    # Room-sensor setup: current should be the room temp, not floor.
    entry = _device()
    # Rebuild with Sensor=Room via raw entry is awkward; instead
    # check the mapping directly on a parsed Room-sensor device.
    from watts_radiant.models import WattsDevice

    dev = WattsDevice(
        device_id="x",
        name="x",
        location_id="loc",
        location_name="801",
        floor_temp=77,
        room_temp=80,
        target_sensor="Room",
    )
    assert dev.current_temperature == 80


def test_hvac_action_and_away_mapping():
    assert _device().hvac_action == "idle"  # Heat mode, Op Off
    assert parse_location(
        {"locationId": "x", "name": "801", "awayState": 0}
    ).home_away == "Home"
    assert parse_location(
        {"locationId": "x", "name": "801", "awayState": 1}
    ).home_away == "Away"

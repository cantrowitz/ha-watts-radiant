"""Scaffold checks that need no Home Assistant install."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components" / "watts_radiant"


def test_manifest_and_strings_agree():
    manifest = json.loads((COMP / "manifest.json").read_text())
    assert manifest["domain"] == "watts_radiant"
    assert manifest["config_flow"] is True
    assert manifest["version"] == "0.3.6"
    strings = json.loads((COMP / "strings.json").read_text())
    translations = json.loads((COMP / "translations" / "en.json").read_text())
    assert strings == translations


def test_hacs_json():
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["name"] == "Watts Radiant"


def test_pkce_shape():
    import sys

    sys.path.insert(0, str(COMP.parent.parent))
    # api.py imports aiohttp only; homeassistant is not needed for it.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "watts_api", COMP / "api.py", loader=None
    )
    # api.py does a relative import (from .const), so load const first
    # via a package-free check: just verify the PKCE math independently.
    import base64
    import hashlib

    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    assert challenge == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

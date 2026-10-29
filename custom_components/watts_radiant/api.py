"""Watts Home auth + API client.

Auth — Azure AD B2C, authorization code + PKCE, from Adam's captures.
Auth requests run over curl_cffi, NOT aiohttp: the B2C gateway
rejects aiohttp's SelfAsserted POST (VM HTTP 400, HA cannot_connect),
while the identical flow over libcurl succeeded live Oct 28, 2026.
The home.watts.com API stays on aiohttp.

1. GET {authority}/oauth2/v2.0/authorize
   response_type=code, client_id (Watts Home app), redirect_uri
   msal<client_id>://auth, scope wattsapiresi/manage + offline_access
   + openid + profile, code_challenge (S256), prompt=login.
   The response sets the B2C session cookies and embeds, in the page
   script, SETTINGS.csrf and SETTINGS.transId
   ("StateProperties=...").
2. POST {authority-host}/SelfAsserted?tx=<transId>&p=<policy>
   with header X-CSRF-TOKEN: <csrf> and form body
   request_type=RESPONSE&signInName=<email>&password=<password>.
   HTTP 200 with a small JSON body means the credentials were
   accepted (the app's JS then follows the "confirmed" step).
3. GET the B2C "confirmed" page for this policy:
   https://login.watts.io/{tenant}/{policy}/api/
   CombinedSigninAndSignup/confirmed?rememberMe=false
   &csrf_token=<csrf>&tx=<transId>&p=<policy>
   (note: NO /tfp/ prefix on this path — that was a bug in the
   first scaffold). The response is an "Object moved" HTML page
   whose link href is the msal://auth URL, URL-encoded, carrying
   state, trustFrameworkPolicy, client_info and code. The code is
   parsed from that href, not from a Location header. (Confirmed
   by Adam's capture, Oct 28, 2026.)
4. POST {authority}/oauth2/v2.0/token with grant_type=
   authorization_code, code, code_verifier, client_id, scope and
   redirect_uri. Returns access_token (900s), refresh_token (90d),
   id_token.
5. Refresh: POST the same token endpoint with grant_type=
   refresh_token, client_id, scope and refresh_token. (Standard
   OAuth2 refresh for this client; also to verify in a live test.)

API — https://home.watts.com/api, header Api-Version: 2.0,
Authorization: Bearer <access_token>:
  GET User/Details  — default location + defaultLocationDevices
  GET Location      — locations, for grouping ("801")
  GET Location/{id}/Devices — full thermostat state per device

No credentials, tokens, cookies, or per-session values are stored
in this repository. Tokens live only in the HA config entry at
runtime (HA storage), and the password is discarded after login.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

try:
    from curl_cffi.requests import AsyncSession as CurlSession
except ImportError:  # pragma: no cover
    CurlSession = None

_LOGGER = logging.getLogger(__name__)

from .const import (
    B2C_AUTHORITY,
    B2C_CLIENT_ID,
    B2C_POLICY,
    B2C_REDIRECT_URI,
    B2C_SCOPE,
)

API_BASE = "https://home.watts.com/api"
API_VERSION = "2.0"


class WattsAuthError(Exception):
    """Raised when Watts login or API access fails."""


class WattsInvalidAuth(WattsAuthError):
    """Credentials were rejected by Watts."""


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds when access_token expires

    @property
    def expired(self) -> bool:
        # Refresh 60s early so a poll never races expiry.
        return time.time() >= self.expires_at - 60

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Tokens":
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=float(data["expires_at"]),
        )

    @classmethod
    def from_token_response(cls, data: dict) -> "Tokens":
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=time.time() + int(data.get("expires_in", 900)),
        )


@dataclass
class PkcePair:
    verifier: str
    challenge: str


def generate_pkce() -> PkcePair:
    """Generate a fresh PKCE verifier/challenge pair (S256)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return PkcePair(verifier=verifier, challenge=challenge)


# The Watts Home app is an Android WebView (MSAL Xamarin). B2C
# serves the same page regardless of UA, but the SelfAsserted
# sign-in — the endpoint Adam warned is the key one, not the
# authorize page HTML — is sent by that WebView, so send its
# headers too: Origin/Referer on the POST, and the app's
# x-client-* params on the authorize URL.
APP_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 17; sdk_gphone64_arm64 "
    "Build/CE2A.260420.051.A3; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/145.0.7632.218 "
    "Mobile Safari/537.36"
)
# WebView client-hint / fetch headers, as in Adam's SelfAsserted
# and confirmed captures (Oct 28, 2026).
APP_SEC_CH_UA = '"Not:A-Brand";v="99", "Android WebView";v="145", "Chromium";v="145"'
APP_FETCH_XHR = {
    "sec-ch-ua": APP_SEC_CH_UA,
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}
APP_FETCH_DOC = {
    "sec-ch-ua": APP_SEC_CH_UA,
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def build_authorize_url(
    pkce: PkcePair, state: str, client_request_id: str | None = None
) -> str:
    """Build the B2C authorize URL for the Watts Home app client."""
    params = {
        "scope": B2C_SCOPE,
        "response_type": "code",
        "client_id": B2C_CLIENT_ID,
        "redirect_uri": B2C_REDIRECT_URI,
        "client-request-id": client_request_id or str(uuid.uuid4()),
        "prompt": "login",
        "code_challenge": pkce.challenge,
        "code_challenge_method": "S256",
        "state": state,
        "client_info": "1",
        "x-client-SKU": "MSAL.Xamarin.Android",
        "x-client-Ver": "4.66.1.0",
        "x-client-OS": "37",
        "haschrome": "1",
    }
    return f"{B2C_AUTHORITY}/oauth2/v2.0/authorize?{urlencode(params)}"


def extract_b2c_page_params(page_html: str) -> tuple[str, str]:
    """Extract csrf and transId from a B2C authorize page.

    The page embeds SETTINGS = { "csrf": "...", "transId":
    "StateProperties=..." }. Both are per-session and must come
    from the live page, never from a capture.
    """
    csrf_match = re.search(r'"csrf":\s*"([^"]+)"', page_html)
    trans_match = re.search(r'"transId":\s*"([^"]+)"', page_html)
    if not csrf_match or not trans_match:
        raise WattsAuthError(
            "Could not find B2C csrf/transId in the sign-in page"
        )
    return csrf_match.group(1), trans_match.group(1)


def extract_code_from_redirect(location: str) -> str:
    """Extract the authorization code from an msal://auth redirect."""
    query = parse_qs(urlparse(location).query)
    codes = query.get("code")
    if not codes:
        raise WattsAuthError(
            f"B2C redirect did not carry an authorization code: {location[:80]}"
        )
    return codes[0]


def extract_code_from_confirmed_html(page_html: str) -> str:
    """Extract the code from a B2C 'Object moved' confirmed page.

    The page contains <a href="msal<client-id>%3a%2f%2fauth%2f%3f
    state%3d...%26code%3d...">here</a> — i.e. the whole msal URL is
    URL-encoded inside the href. Unquote it first, then parse.
    Also accepts a plain msal://auth?code=... href.
    """
    from urllib.parse import unquote

    href_match = re.search(r'href="([^"]+)"', page_html)
    if not href_match:
        raise WattsAuthError("Confirmed page contained no redirect link")
    href = unquote(href_match.group(1))
    return extract_code_from_redirect(href)


def build_confirmed_url(csrf: str, trans_id: str) -> str:
    """Build the B2C confirmed URL (no /tfp/ prefix, no diags)."""
    tenant = B2C_AUTHORITY.split("/tfp/")[1].rsplit("/", 1)[0]
    params = {
        "rememberMe": "false",
        "csrf_token": csrf,
        "tx": trans_id,
        "p": B2C_POLICY,
    }
    return (
        f"https://login.watts.io/{tenant}/{B2C_POLICY}/api/"
        f"CombinedSigninAndSignup/confirmed?{urlencode(params)}"
    )


class WattsAuthClient:
    """B2C login client, using curl_cffi (not aiohttp) for auth.

    Why: the B2C gateway rejects the SelfAsserted POST from aiohttp
    (VM: HTTP 400 with no B2C JSON, and HA config flow: cannot_connect),
    while the identical flow over libcurl succeeds live — verified
    Oct 28, 2026: authorize 200, SelfAsserted 200, confirmed 302,
    token 200, Locations 200, Devices 200 (count 2). The home.watts.com
    API itself stays on aiohttp; only B2C auth uses curl_cffi.
    One instance per login attempt; the session is created per call.
    """

    def __init__(self, session=None) -> None:
        # session is accepted for call-site compatibility but ignored:
        # auth always runs on its own curl_cffi session.
        self._ignored_session = session

    def _cookie_params(self, cookies) -> tuple[str, str] | None:
        """csrf + transId from B2C cookies, or None if absent."""
        try:
            csrf = cookies.get("x-ms-cpim-csrf")
            trans = cookies.get("x-ms-cpim-trans")
            if not csrf or not trans:
                return None
            padded = trans + "=" * (-len(trans) % 4)
            cid = json.loads(base64.b64decode(padded))["C_ID"]
            tid = base64.urlsafe_b64encode(
                json.dumps({"TID": cid}, separators=(",", ":")).encode()
            ).decode()
            return csrf, f"StateProperties={tid}"
        except Exception:
            return None

    async def authenticate(self, email: str, password: str) -> Tokens:
        """Full login: authorize -> SelfAsserted -> confirmed -> token."""
        if CurlSession is None:
            raise WattsAuthError("curl_cffi is not installed (manifest requirement)")
        pkce = generate_pkce()
        state = str(uuid.uuid4())
        client_request_id = str(uuid.uuid4())
        tenant = B2C_AUTHORITY.split("/tfp/")[1].rsplit("/", 1)[0]
        authorize_url = build_authorize_url(pkce, state, client_request_id)

        async with CurlSession(impersonate="chrome") as session:
            # 1. Authorize page: cookies + csrf/transId.
            resp = await session.get(
                authorize_url,
                headers={
                    "User-Agent": APP_USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "X-Requested-With": "com.watts.home",
                },
            )
            if resp.status_code != 200:
                _LOGGER.warning("Watts authorize failed: HTTP %s", resp.status_code)
                raise WattsAuthError(f"B2C authorize failed: HTTP {resp.status_code}")
            page = resp.text
            try:
                csrf, trans_id = extract_b2c_page_params(page)
            except WattsAuthError:
                cookie_params = self._cookie_params(session.cookies)
                if cookie_params is None:
                    raise
                csrf, trans_id = cookie_params
                _LOGGER.debug("B2C params from cookies (page extraction fell back)")

            # 2. SelfAsserted sign-in.
            self_asserted_url = (
                f"https://login.watts.io/{tenant}/{B2C_POLICY}/SelfAsserted"
                f"?tx={trans_id}&p={B2C_POLICY}"
            )
            resp = await session.post(
                self_asserted_url,
                data={
                    "request_type": "RESPONSE",
                    "signInName": email,
                    "password": password,
                },
                headers={
                    "User-Agent": APP_USER_AGENT,
                    "X-CSRF-TOKEN": csrf,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Origin": "https://login.watts.io",
                    "Referer": authorize_url,
                    **APP_FETCH_XHR,
                },
            )
            if resp.status_code != 200:
                # B2C returning non-200 here is a credential rejection
                # in practice; keep the invalid_auth mapping.
                _LOGGER.warning("Watts SelfAsserted rejected: HTTP %s", resp.status_code)
                raise WattsInvalidAuth(
                    f"Watts sign-in rejected: HTTP {resp.status_code}"
                )
            body = resp.text
            if '"status":400' in body or '"error"' in body.lower():
                raise WattsInvalidAuth("Watts sign-in rejected by B2C")

            # 3. Confirmed step: 302 Location is the msal://auth URL;
            # fall back to the Object-moved HTML href.
            resp = await session.get(
                build_confirmed_url(csrf, trans_id),
                allow_redirects=False,
                headers={
                    "User-Agent": APP_USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": authorize_url,
                    "X-Requested-With": "com.watts.home",
                    **APP_FETCH_DOC,
                },
            )
            location = resp.headers.get("Location", "")
            if location.startswith(B2C_REDIRECT_URI):
                code = extract_code_from_redirect(location)
            else:
                code = extract_code_from_confirmed_html(resp.text)

            # 4. Code -> tokens.
            return await self.exchange_code(
                code, pkce.verifier, client_request_id, session
            )

    async def exchange_code(
        self, code: str, verifier: str, client_request_id: str | None = None,
        session=None,
    ) -> Tokens:
        """Exchange an authorization code for tokens."""
        if CurlSession is None:
            raise WattsAuthError("curl_cffi is not installed (manifest requirement)")
        own_session = session is None
        if own_session:
            session = CurlSession(impersonate="chrome")
        try:
            resp = await session.post(
                f"{B2C_AUTHORITY}/oauth2/v2.0/token?haschrome=1",
                data={
                    "client_id": B2C_CLIENT_ID,
                    "scope": B2C_SCOPE,
                    "client_info": "1",
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": B2C_REDIRECT_URI,
                    "code_verifier": verifier,
                },
                headers={
                    "Accept": "application/json",
                    "client-request-id": client_request_id or str(uuid.uuid4()),
                    "return-client-request-id": "true",
                    "x-client-SKU": "MSAL.Xamarin.Android",
                    "x-client-Ver": "4.66.1.0",
                    "x-client-OS": "37",
                    "x-ms-lib-capability": "retry-after, h429",
                },
            )
            data = resp.json()
            if resp.status_code != 200:
                _LOGGER.warning("Watts token exchange failed: HTTP %s", resp.status_code)
                raise WattsAuthError(
                    f"B2C token exchange failed: HTTP {resp.status_code}"
                )
            return Tokens.from_token_response(data)
        finally:
            if own_session:
                await session.close()

    async def refresh(self, refresh_token: str) -> Tokens:
        """Refresh tokens with a refresh token."""
        if CurlSession is None:
            raise WattsAuthError("curl_cffi is not installed (manifest requirement)")
        async with CurlSession(impersonate="chrome") as session:
            resp = await session.post(
                f"{B2C_AUTHORITY}/oauth2/v2.0/token?haschrome=1",
                data={
                    "client_id": B2C_CLIENT_ID,
                    "scope": B2C_SCOPE,
                    "client_info": "1",
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "redirect_uri": B2C_REDIRECT_URI,
                },
                headers={
                    "Accept": "application/json",
                    "client-request-id": str(uuid.uuid4()),
                    "return-client-request-id": "true",
                    "x-client-SKU": "MSAL.Xamarin.Android",
                    "x-client-Ver": "4.66.1.0",
                    "x-client-OS": "37",
                    "x-ms-lib-capability": "retry-after, h429",
                },
            )
            data = resp.json()
            if resp.status_code != 200:
                _LOGGER.warning("Watts token refresh failed: HTTP %s", resp.status_code)
                raise WattsInvalidAuth(
                    f"Watts token refresh failed: HTTP {resp.status_code}"
                )
            return Tokens.from_token_response(data)


def away_state_payload(away: bool) -> dict:
    """Payload for a location Home/Away set: awayState 1 = Away, 0 = Home."""
    return {"awayState": 1 if away else 0}


def temp_settings_payload(temperature: float, schedule_enabled: bool) -> dict:
    """Settings payload for a temperature set.

    Schedule on -> HeatHold; schedule off -> Heat.
    Both verified live from Adam's captures Oct 28, 2026.
    """
    value = int(round(temperature))
    key = "HeatHold" if schedule_enabled else "Heat"
    return {"Settings": {key: value}}


class WattsApiClient:
    """Read-only Watts API client (home.watts.com)."""

    def __init__(self, session: aiohttp.ClientSession, tokens: Tokens) -> None:
        self._session = session
        self.tokens = tokens

    def _headers(self) -> dict:
        return {
            "Api-Version": API_VERSION,
            "Authorization": f"Bearer {self.tokens.access_token}",
        }

    async def _get(self, path: str) -> dict:
        async with self._session.get(f"{API_BASE}{path}", headers=self._headers()) as resp:
            if resp.status == 401:
                raise WattsInvalidAuth("Watts access token rejected (401)")
            if resp.status != 200:
                raise WattsAuthError(f"Watts API {path} failed: HTTP {resp.status}")
            return await resp.json(content_type=None)

    async def get_user_details(self) -> dict:
        """GET /User/Details — body contains default location/devices."""
        data = await self._get("/User/Details")
        return data.get("body", data)

    async def get_locations(self) -> list[dict]:
        """GET /Location — body is a list of locations."""
        data = await self._get("/Location")
        body = data.get("body", data)
        return body if isinstance(body, list) else []

    async def _patch(self, path: str, payload: dict) -> dict:
        async with self._session.patch(
            f"{API_BASE}{path}", json=payload, headers=self._headers()
        ) as resp:
            if resp.status == 401:
                raise WattsInvalidAuth("Watts access token rejected (401)")
            if resp.status != 200:
                raise WattsAuthError(f"Watts API {path} failed: HTTP {resp.status}")
            return await resp.json(content_type=None)

    async def set_device_mode(self, device_id: str, mode: str) -> dict:
        """PATCH /Device/{id} Settings.Mode — mode is "Off" or "Heat".

        Both directions verified from Adam's captures Oct 28, 2026:
        Mode Off -> Target Active 0 / Heat null; Mode Heat is the
        symmetric payload. No other Settings fields are sent here.
        """
        if mode not in ("Off", "Heat"):
            raise ValueError(f"Unknown Watts mode: {mode}")
        data = await self._patch(f"/Device/{device_id}", {"Settings": {"Mode": mode}})
        return data.get("body", data)

    async def set_device_temperature(
        self, device_id: str, temperature: float, schedule_enabled: bool
    ) -> dict:
        """PATCH /Device/{id} Settings to set the heat target.

        Verified from Adam's captures Oct 28, 2026: schedule on ->
        {"Settings": {"HeatHold": 66}}; schedule off ->
        {"Settings": {"Heat": 84}}.
        """
        payload = temp_settings_payload(temperature, schedule_enabled)
        data = await self._patch(f"/Device/{device_id}", payload)
        return data.get("body", data)

    async def cancel_device_hold(self, device_id: str) -> dict:
        """PATCH /Device/{id} Settings.HeatHold = null: cancel override.

        Verified from Adam's capture Oct 28, 2026 ("canceling
        override"): {"Settings": {"HeatHold": null}}. After this,
        the thermostat returns to Following Schedule.
        """
        data = await self._patch(f"/Device/{device_id}", {"Settings": {"HeatHold": None}})
        return data.get("body", data)

    async def set_schedule_enabled(self, device_id: str, enabled: bool) -> dict:
        """PATCH /Device/{id} Settings.SchedEnable — "On" or "Off".

        Verified from Adam's capture Oct 28, 2026:
        {"Settings": {"SchedEnable": "Off"}} turns the schedule off
        (the schedule-setting payload also carries SchedEnable "On").
        """
        data = await self._patch(
            f"/Device/{device_id}",
            {"Settings": {"SchedEnable": "On" if enabled else "Off"}},
        )
        return data.get("body", data)

    async def set_location_away_state(self, location_id: str, away: bool) -> dict:
        """PATCH /Location/{id}/State with awayState 1 = Away, 0 = Home.

        Shape (bare awayState, no Settings wrapper) comes from
        another Watts Home implementation, NOT from Adam's captures
        yet — untested on his system until he flips it in HA.
        """
        data = await self._patch(
            f"/Location/{location_id}/State", away_state_payload(away)
        )
        return data.get("body", data)

    async def get_location_devices(self, location_id: str) -> list[dict]:
        """GET /Location/{id}/Devices — full thermostat state."""
        data = await self._get(f"/Location/{location_id}/Devices")
        body = data.get("body", data)
        return body if isinstance(body, list) else []

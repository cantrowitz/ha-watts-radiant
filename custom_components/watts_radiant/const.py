"""Constants for the Watts Radiant integration."""

DOMAIN = "watts_radiant"
PLATFORMS: list[str] = ["climate", "sensor", "switch"]

# Azure AD B2C (Watts Home app, com.watts.home) — from Adam's login capture.
# These are the app's public OAuth client parameters, not user credentials.
# The per-session values (code_challenge, state, csrf, transId) are generated
# fresh on every login and are never stored here.
B2C_TENANT = "wattsb2cap02.onmicrosoft.com"
B2C_POLICY = "B2C_1A_Residential_UnifiedSignUpOrSignIn"
B2C_AUTHORITY = (
    f"https://login.watts.io/tfp/{B2C_TENANT}/{B2C_POLICY}"
)
B2C_CLIENT_ID = "4b3a6465-94dd-47c2-976c-18bc29c53c2f"
B2C_REDIRECT_URI = f"msal{B2C_CLIENT_ID}://auth"
B2C_SCOPE = (
    f"https://{B2C_TENANT}/wattsapiresi/manage "
    "offline_access openid profile"
)
# Token endpoint is resolved from the B2C OpenID discovery document at
# {B2C_AUTHORITY}/v2.0/.well-known/openid-configuration — see api.py.
# It is filled in once the next captured calls confirm it; do not hardcode
# a token URL from a different policy.

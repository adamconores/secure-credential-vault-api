"""URL prefixes shared by the routers and the OAuth2 scheme."""

API_V1_PREFIX = "/api/v1"
AUTH_PREFIX = "/auth"
LOGIN_PATH = "/login"
TOKEN_URL = f"{API_V1_PREFIX}{AUTH_PREFIX}{LOGIN_PATH}"
VAULT_ITEMS_PREFIX = "/vault/items"

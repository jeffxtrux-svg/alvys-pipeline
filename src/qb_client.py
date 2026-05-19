"""QuickBooks Online OAuth 2.0 client with automatic token refresh.

Handles:
- Initial token exchange (refresh_token -> access_token + new refresh_token)
- Automatic re-auth on 401
- Exposes new_refresh_token so main.py can rotate the GitHub Secret after each run
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Any

import requests

log = logging.getLogger("qb_client")

TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
BASE_URL = "https://quickbooks.api.intuit.com/v3/company"
MINOR_VERSION = 75


class QBClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        realm_id: str,
        refresh_token: str,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.realm_id = realm_id
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self.new_refresh_token: str | None = None  # populated after first refresh

    def _auth_header(self) -> str:
        credentials = f"{self.client_id}:{self.client_secret}"
        return "Basic " + base64.b64encode(credentials.encode()).decode()

    def _refresh(self) -> None:
        log.info("Refreshing QB access token (realm %s)…", self.realm_id)
        resp = requests.post(
            TOKEN_URL,
            headers={
                "Authorization": self._auth_header(),
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": self._refresh_token},
            timeout=30,
        )
        if resp.status_code != 200:
            log.error("Token refresh failed [%s]: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()

        data = resp.json()
        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600) - 60
        self.new_refresh_token = self._refresh_token
        log.info("Token refreshed ✓")

    def _ensure_token(self) -> str:
        if not self._access_token or time.time() >= self._token_expires_at:
            self._refresh()
        return self._access_token  # type: ignore[return-value]

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        token = self._ensure_token()
        url = f"{BASE_URL}/{self.realm_id}/{path}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        resp = requests.get(url, headers=headers, params=params or {}, timeout=60)

        if resp.status_code == 401:
            # Force one refresh and retry
            self._access_token = None
            token = self._ensure_token()
            headers["Authorization"] = f"Bearer {token}"
            resp = requests.get(url, headers=headers, params=params or {}, timeout=60)

        if resp.status_code != 200:
            log.error("QB API [%s] %s: %s", resp.status_code, url, resp.text[:500])
            resp.raise_for_status()

        return resp.json()

"""OAuth 2.1 (PKCE, public client, dynamic registration) against mcp.silpo.ua."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import LocalOAuth2ImplementationWithPkce

from .const import DOMAIN, MCP_URL, OAUTH_METADATA_URL

_LOGGER = logging.getLogger(__name__)


async def async_fetch_metadata(hass: HomeAssistant) -> dict[str, Any]:
    async with async_get_clientsession(hass).get(OAUTH_METADATA_URL) as resp:
        resp.raise_for_status()
        return await resp.json()


async def async_register_client(hass: HomeAssistant, redirect_uri: str, meta: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """Dynamic Client Registration -> (client_id, metadata)."""
    meta = meta or await async_fetch_metadata(hass)
    body = {"client_name": "Home Assistant", "redirect_uris": [redirect_uri], "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": "none"}
    async with async_get_clientsession(hass).post(meta["registration_endpoint"], json=body) as resp:
        if resp.status not in (200, 201):
            raise RuntimeError(f"registration failed: HTTP {resp.status} {(await resp.text())[:200]}")
        data = await resp.json()
    return data["client_id"], meta


class SilpoOAuth2Implementation(LocalOAuth2ImplementationWithPkce):
    def __init__(self, hass: HomeAssistant, client_id: str, meta: dict[str, Any]) -> None:
        super().__init__(hass, DOMAIN, client_id, meta["authorization_endpoint"], meta["token_endpoint"], client_secret="")

    @property
    def name(self) -> str:
        return "Silpo account"

    @property
    def extra_authorize_data(self) -> dict:
        return {**super().extra_authorize_data, "resource": MCP_URL}

    async def _token_request(self, data: dict) -> dict:
        # public client: no client_secret; RFC 8707 resource indicator
        data = {k: v for k, v in data.items() if k != "client_secret"}
        data["client_id"] = self.client_id
        data["resource"] = MCP_URL
        session = async_get_clientsession(self.hass)
        async with session.post(self.token_url, data=data) as resp:
            if resp.status >= 400:
                _LOGGER.error("Silpo token request failed: %s %s", resp.status, (await resp.text())[:300])
            resp.raise_for_status()
            return await resp.json()

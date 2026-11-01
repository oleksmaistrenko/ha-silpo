"""Silpo purchases — forecast & habits from in-store receipts via the official Silpo MCP."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SilpoMcpClient
from .const import CONF_CLIENT_ID, DOMAIN
from .coordinator import SilpoCoordinator
from .oauth import SilpoOAuth2Implementation, async_fetch_metadata
from .store import ReceiptStore

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    meta = await async_fetch_metadata(hass)
    impl = SilpoOAuth2Implementation(hass, entry.data[CONF_CLIENT_ID], meta)
    config_entry_oauth2_flow.async_register_implementation(hass, DOMAIN, impl)
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, impl)

    async def token() -> str:
        await session.async_ensure_token_valid()
        return session.token["access_token"]

    client = SilpoMcpClient(async_get_clientsession(hass), token)
    store = ReceiptStore(hass, entry.entry_id)
    await store.async_load()
    coordinator = SilpoCoordinator(hass, entry, client, store)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return ok

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import config_entry_oauth2_flow

from .const import CONF_CLIENT_ID, DOMAIN
from .oauth import SilpoOAuth2Implementation, async_fetch_metadata, async_register_client

_LOGGER = logging.getLogger(__name__)


class SilpoConfigFlow(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    DOMAIN = DOMAIN
    VERSION = 1
    _client_id: str | None = None

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    async def _register_impl(self, client_id: str | None = None) -> None:
        if client_id:
            meta = await async_fetch_metadata(self.hass)
        else:
            meta = await async_fetch_metadata(self.hass)
            redirect = SilpoOAuth2Implementation(self.hass, "pending", meta).redirect_uri
            client_id, meta = await async_register_client(self.hass, redirect, meta)
        self._client_id = client_id
        config_entry_oauth2_flow.async_register_implementation(self.hass, DOMAIN, SilpoOAuth2Implementation(self.hass, client_id, meta))

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        try:
            await self._register_impl()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Silpo OAuth registration failed: %s", err)
            return self.async_abort(reason="missing_configuration")
        return await super().async_step_user(user_input)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        await self._register_impl(entry_data.get(CONF_CLIENT_ID))
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict) -> ConfigFlowResult:
        data[CONF_CLIENT_ID] = self._client_id
        if self.source == "reauth":
            entry = self._get_reauth_entry()
            return self.async_update_reload_and_abort(entry, data=data)
        return self.async_create_entry(title="Silpo", data=data)

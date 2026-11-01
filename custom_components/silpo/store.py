"""Persistent receipt store (HA Store, JSON in .storage/). Grows beyond the API's 12-month window."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .engine import receipt_key


class ReceiptStore:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry_id}")
        self.receipts: dict[str, dict] = {}
        self.meta: dict[str, Any] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.receipts = data.get("receipts", {})
        self.meta = data.get("meta", {})

    async def async_save(self) -> None:
        await self._store.async_save({"receipts": self.receipts, "meta": self.meta})

    def merge(self, receipts: list[dict]) -> int:
        """Add new receipts; returns how many were new."""
        new = 0
        for r in receipts:
            k = receipt_key(r)
            if k not in self.receipts:
                new += 1
            self.receipts[k] = r      # overwrite: catalogProduct links may refresh
        return new

    def all(self) -> list[dict]:
        return sorted(self.receipts.values(), key=lambda r: r["createdAt"])

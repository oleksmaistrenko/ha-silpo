"""Fetch receipts + promos, run the engine, expose results."""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SilpoAuthError, SilpoApiError, SilpoMcpClient
from .const import (ACTIONABLE, BACKFILL_DAYS, DEFAULT_LOOKBACK_DAYS, DOMAIN, EVENT_PROMO_MATCH,
                    PROMO_INTERVAL_HOURS, UPDATE_INTERVAL_HOURS)
from .engine import analyze
from .store import ReceiptStore

_LOGGER = logging.getLogger(__name__)


class SilpoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: SilpoMcpClient, store: ReceiptStore) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(hours=UPDATE_INTERVAL_HOURS), config_entry=entry)
        self.client = client
        self.store = store
        self.entry = entry
        self._branches: list[dict] = []
        self._promo: dict[str, Any] = {"checked": None, "matches": [], "promotions": [], "personal_promos": [], "coupons": []}
        self.auth_ok = True

    # ---------- helpers ----------
    async def _branch_ctx(self) -> dict:
        if not self._branches:
            self._branches = await self.client.list_branches()
        home = self.home_branch_external_ids()
        for b in self._branches:
            if b.get("externalId") in home:
                return self.client.synthetic_context(b["branchId"])
        pick = next((b for b in self._branches if b.get("hasPickup")), self._branches[0])
        return self.client.synthetic_context(pick["branchId"])

    def home_branch_external_ids(self) -> list[str]:
        c = Counter(str(int(r["filId"])) for r in self.store.receipts.values())
        return [k for k, _ in c.most_common(2)]

    def home_branches(self) -> list[dict]:
        ids = self.home_branch_external_ids()
        return [b for b in self._branches if b.get("externalId") in ids]

    # ---------- update ----------
    async def _async_update_data(self) -> dict[str, Any]:
        try:
            ctx = await self._branch_ctx()
            now = datetime.now(timezone.utc)
            if not self.store.meta.get("backfilled"):
                start = now - timedelta(days=BACKFILL_DAYS)
                receipts = []
                cur = start
                while cur < now:
                    nxt = min(cur + timedelta(days=90), now + timedelta(days=1))
                    receipts += await self.client.offline_orders(ctx, cur.strftime("%Y-%m-%dT00:00:00"), nxt.strftime("%Y-%m-%dT00:00:00"))
                    cur = nxt
                self.store.meta["backfilled"] = now.isoformat()
            else:
                lookback = self.entry.options.get("lookback_days", DEFAULT_LOOKBACK_DAYS)
                receipts = await self.client.offline_orders(ctx, (now - timedelta(days=lookback)).strftime("%Y-%m-%dT00:00:00"),
                                                            (now + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00"))
            new = self.store.merge(receipts)
            self.store.meta["last_sync"] = now.isoformat()
            self.store.meta["last_new"] = new
            await self.store.async_save()
            self.auth_ok = True

            analysis = analyze(self.store.all(), date.today())

            last = self._promo.get("checked")
            if not last or (now - datetime.fromisoformat(last)) > timedelta(hours=PROMO_INTERVAL_HOURS):
                try:
                    await self._refresh_promos(analysis)
                except SilpoApiError as err:
                    _LOGGER.warning("promo refresh failed: %s", err)
            analysis["promo"] = self._promo
            analysis["sync"] = {"last_sync": self.store.meta["last_sync"], "new_receipts": new, "stored_receipts": len(self.store.receipts),
                                "home_branches": [b.get("address") for b in self.home_branches()]}
            return analysis
        except SilpoAuthError as err:
            self.auth_ok = False
            raise ConfigEntryAuthFailed from err
        except SilpoApiError as err:
            raise UpdateFailed(str(err)) from err

    async def _refresh_promos(self, analysis: dict) -> None:
        by_lager = {p["lager_id"]: p for p in analysis["products"]}
        matches, promotions = [], []
        seen: set[int] = set()
        for b in self.home_branches()[:2]:
            ctx = self.client.synthetic_context(b["branchId"])
            promos = await self.client.call_tool("silpo_get_promotions", ctx)
            promotions.append({"branch": b.get("address"), "promotions": [{"code": p["code"], "title": p["title"], "count": p["productCount"]} for p in promos.get("promotions") or []]})
            for pr in await self.client.promo_products(ctx):
                lid = pr.get("externalProductId")
                if not lid or int(lid) not in by_lager or int(lid) in seen:
                    continue
                seen.add(int(lid))
                h = by_lager[int(lid)]
                old = pr.get("oldPrice")
                matches.append({"lager_id": int(lid), "name": h["name"], "status": h["status"], "buys": h["buys"], "due_in": h["due_in"],
                                "price": pr.get("price"), "old_price": old, "discount_pct": round((1 - pr["price"] / old) * 100) if old else None,
                                "special_prices": pr.get("specialPrices"), "branch": b.get("address"), "slug": pr.get("slug")})
        order = {s: i for i, s in enumerate(("overdue", "due", "soon", "stocked", "long_cycle", "irregular", "lapsed", "occasional"))}
        matches.sort(key=lambda m: (order.get(m["status"], 9), -(m["discount_pct"] or 0)))
        personal = await self.client.call_tool("silpo_get_my_promos", {})
        coupons = await self.client.call_tool("silpo_get_my_coupons", {})
        prev = {m["lager_id"] for m in self._promo.get("matches", [])}
        self._promo = {"checked": datetime.now(timezone.utc).isoformat(), "matches": matches, "promotions": promotions,
                       "personal_promos": [{k: p.get(k) for k in ("promoId", "selected", "endDate", "description", "rewardText")} for p in personal.get("promos") or []],
                       "coupons": [{k: c.get(k) for k in ("id", "active", "endDate", "description", "rewardText", "promoId")} for c in coupons.get("coupons") or []]}
        for m in matches:
            if m["lager_id"] not in prev and m["status"] in ACTIONABLE + ("stocked", "long_cycle"):
                self.hass.bus.async_fire(EVENT_PROMO_MATCH, m)

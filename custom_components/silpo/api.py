"""Minimal MCP Streamable-HTTP client for the official Silpo MCP, on aiohttp (no extra deps).

Handles initialize / tools/call over JSON-RPC, SSE or JSON responses, Mcp-Session-Id, 401/429.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import aiohttp

_LOGGER = logging.getLogger(__name__)
MCP_URL = "https://mcp.silpo.ua/mcp"
PROTOCOL = "2025-06-18"


class SilpoAuthError(Exception):
    """Token rejected (401) — re-auth required."""


class SilpoApiError(Exception):
    """Any other API failure."""


class SilpoMcpClient:
    def __init__(self, session: aiohttp.ClientSession, token_getter: Callable[[], Awaitable[str]], url: str = MCP_URL) -> None:
        self._session = session
        self._get_token = token_getter
        self._url = url
        self._mcp_session: str | None = None
        self._id = 0
        self._lock = asyncio.Lock()

    # ---------------- transport ----------------
    async def _post(self, payload: dict, *, retries: int = 3) -> dict | None:
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self._mcp_session:
            headers["Mcp-Session-Id"] = self._mcp_session
        for attempt in range(retries):
            async with self._session.post(self._url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 401:
                    raise SilpoAuthError(await resp.text())
                if resp.status == 429:
                    await asyncio.sleep(2 ** attempt * 2)
                    continue
                if resp.status == 404 and self._mcp_session:
                    self._mcp_session = None   # session expired server-side; caller re-inits
                    raise SilpoApiError("mcp session expired")
                if resp.status >= 400:
                    raise SilpoApiError(f"HTTP {resp.status}: {(await resp.text())[:300]}")
                if sid := resp.headers.get("Mcp-Session-Id"):
                    self._mcp_session = sid
                if resp.status == 202 or "id" not in payload:
                    return None
                ctype = resp.headers.get("Content-Type", "")
                if ctype.startswith("text/event-stream"):
                    return await self._read_sse(resp, payload["id"])
                return await resp.json(content_type=None)
        raise SilpoApiError("rate limited")

    @staticmethod
    async def _read_sse(resp: aiohttp.ClientResponse, want_id: int) -> dict:
        data_lines: list[str] = []
        async for raw in resp.content:
            line = raw.decode().rstrip("\r\n")
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
            elif line == "" and data_lines:
                try:
                    msg = json.loads("\n".join(data_lines))
                except json.JSONDecodeError:
                    msg = None
                data_lines = []
                if isinstance(msg, dict) and msg.get("id") == want_id:
                    return msg
        if data_lines:
            msg = json.loads("\n".join(data_lines))
            if msg.get("id") == want_id:
                return msg
        raise SilpoApiError("no JSON-RPC response in SSE stream")

    async def _rpc(self, method: str, params: dict | None = None) -> Any:
        self._id += 1
        msg = await self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        if msg is None:
            return None
        if "error" in msg:
            raise SilpoApiError(f"{method}: {msg['error']}")
        return msg.get("result")

    async def _ensure_init(self) -> None:
        if self._mcp_session:
            return
        await self._rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                       "clientInfo": {"name": "home-assistant-silpo", "version": "0.1.0"}})
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    # ---------------- public ----------------
    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        async with self._lock:
            for attempt in (0, 1):
                try:
                    await self._ensure_init()
                    res = await self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
                    break
                except SilpoApiError as err:
                    if attempt == 0 and "session expired" in str(err):
                        continue
                    raise
        if res.get("isError"):
            raise SilpoApiError(f"{name}: {res.get('content')}")
        if "structuredContent" in res:
            return res["structuredContent"]
        for c in res.get("content") or []:
            if c.get("type") == "text":
                try:
                    return json.loads(c["text"])
                except json.JSONDecodeError:
                    return {"text": c["text"]}
        return res

    async def list_tools(self) -> list[dict]:
        async with self._lock:
            await self._ensure_init()
            return (await self._rpc("tools/list"))["tools"]

    # ---------------- Silpo helpers ----------------
    @staticmethod
    def synthetic_context(branch_id: str) -> dict:
        start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        return {"branchId": branch_id, "deliveryType": "SelfPickup",
                "timeslotStart": start.isoformat(), "timeslotEnd": (start + timedelta(hours=2)).isoformat()}

    async def list_branches(self) -> list[dict]:
        out, off = [], 0
        while True:
            r = await self.call_tool("silpo_list_branches", {"limit": 50, "offset": off})
            items = r.get("branches") or []
            out += items
            if not items or len(out) >= (r.get("meta") or {}).get("total", 0):
                return out
            off += 50

    async def offline_orders(self, ctx: dict, date_start: str, date_end: str) -> list[dict]:
        out, off = [], 0
        while True:
            r = await self.call_tool("silpo_get_my_offline_orders", dict(ctx, limit=10, offset=off, dateStart=date_start, dateEnd=date_end))
            items = r.get("orders") or []
            out += items
            total = (r.get("meta") or {}).get("total", 0)
            if not items or len(out) >= total:
                return out
            off += 10
            await asyncio.sleep(0.2)

    async def promo_products(self, ctx: dict, max_pages: int = 30) -> list[dict]:
        out, off = [], 0
        for _ in range(max_pages):
            r = await self.call_tool("silpo_get_products", dict(ctx, mustHavePromotion=True, inStock=True, limit=100, offset=off))
            items = r.get("products") or []
            out += items
            if not items or len(out) >= (r.get("meta") or {}).get("total", 0):
                break
            off += len(items)
            await asyncio.sleep(0.2)
        return out

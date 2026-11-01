# /// script
# requires-python = ">=3.12"
# dependencies = ["silpo-py-mcp"]
# ///
"""Backfill full offline history in quarterly windows, dedupe, save probe-output/offline_history.json"""
import asyncio, json
from datetime import date
from pathlib import Path
from silpo_py_mcp import SilpoClient
OUT = Path(__file__).resolve().parent.parent / "probe-output"
ctx = json.load(open(OUT / "offline_orders_all.json"))["context"]

def quarters(start=date(2023,1,1), end=date(2026,12,31)):
    y, m = start.year, 1
    while date(y, m, 1) <= end:
        m2, y2 = (m + 3, y) if m < 10 else (1, y + 1)
        yield f"{y:04d}-{m:02d}-01T00:00:00", f"{y2:04d}-{m2:02d}-01T00:00:00"
        y, m = y2, m2

async def main():
    seen, log = {}, []
    async with SilpoClient.for_real_server() as c:
        for s, e in quarters():
            off, got, total = 0, 0, None
            while True:
                r = await c.call_tool("silpo_get_my_offline_orders", dict(ctx, limit=10, offset=off, dateStart=s, dateEnd=e))
                orders = r.get("orders") or []; total = r["meta"]["total"]
                for o in orders:
                    seen[(o["createdAt"], o["filId"], o["sumReg"])] = o
                got += len(orders); off += 10
                if not orders or got >= total: break
                await asyncio.sleep(0.3)
            dates = sorted(o["createdAt"][:10] for o in seen.values() if s <= o["createdAt"] < e)
            line = f"{s[:10]}..{e[:10]}: total={total} fetched={got} in-window={len(dates)} {dates[:1]}..{dates[-1:]}"
            print(line); log.append(line)
    orders = sorted(seen.values(), key=lambda o: o["createdAt"])
    (OUT / "offline_history.json").write_text(json.dumps({"context": ctx, "orders": orders, "log": log}, ensure_ascii=False, indent=2))
    print(f"\n{len(orders)} unique receipts, {orders[0]['createdAt'][:10]} -> {orders[-1]['createdAt'][:10]}")
asyncio.run(main())

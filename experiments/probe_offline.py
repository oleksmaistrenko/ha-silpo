# /// script
# requires-python = ">=3.12"
# dependencies = ["silpo-py-mcp"]
# ///
"""Pull the full in-store (offline) purchase history into probe-output/offline_orders_all.json.
Run:  uv run experiments/probe_offline.py
"""
import asyncio, json, traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from silpo_py_mcp import SilpoClient

OUT = Path(__file__).resolve().parent.parent / "probe-output"
OUT.mkdir(exist_ok=True)

def dump(name, data):
    p = OUT / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    print(f"  -> wrote {p.name} ({p.stat().st_size} bytes)")

async def cart_context(client):
    """Try real cart first; fall back to any branch + SelfPickup + a synthetic timeslot."""
    try:
        mine = await client.call_tool("silpo_get_my_shopping_cart", {})
        dump("my_shopping_cart.json", mine)
        cid = mine.get("shoppingCartId") or (mine.get("cart") or {}).get("id")
        if mine.get("exists", bool(cid)) and cid:
            cart = await client.call_tool("silpo_get_shopping_cart_by_id", {"shoppingCartId": cid})
            dump("shopping_cart_by_id.json", cart)
            def find(obj, key):
                if isinstance(obj, dict):
                    if key in obj and obj[key]: return obj[key]
                    for v in obj.values():
                        r = find(v, key)
                        if r: return r
                if isinstance(obj, list):
                    for v in obj:
                        r = find(v, key)
                        if r: return r
            ts = find(cart, "timeslot") or find(cart, "timeSlot") or {}
            ctx = {"branchId": str(find(cart, "branchId")), "deliveryType": find(cart, "deliveryType"),
                   "timeslotStart": ts.get("start") or ts.get("from"), "timeslotEnd": ts.get("end") or ts.get("to")}
            if all(ctx.values()):
                print("cart context:", ctx); return ctx
            print("cart exists but context incomplete:", ctx)
    except Exception as e:
        print("cart lookup failed:", e)
    branches = await client.call_tool("silpo_list_branches", {"hasPickup": True, "limit": 5})
    dump("branches.json", branches)
    b = (branches.get("branches") or [])[0]
    start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    ctx = {"branchId": str(b.get("branchId") or b.get("id")), "deliveryType": "SelfPickup",
           "timeslotStart": start.isoformat(), "timeslotEnd": (start + timedelta(hours=2)).isoformat()}
    print("fallback context:", ctx, "| branch:", b.get("address") or b.get("name"))
    return ctx

async def main():
    async with SilpoClient.for_real_server() as client:
        ctx = await cart_context(client)
        args = dict(ctx, limit=10, offset=0, dateStart="2015-01-01T00:00:00")
        all_orders, total = [], None
        while True:
            try:
                res = await client.call_tool("silpo_get_my_offline_orders", args)
            except Exception as e:
                print("!!", e); dump("offline_orders_all.error.txt", {"error": str(e), "args": args, "trace": traceback.format_exc()}); break
            if all_orders == []: dump("offline_orders_page0.json", res)
            orders = res.get("orders") or []
            total = (res.get("meta") or {}).get("total", total)
            all_orders += orders
            print(f"  offset {args['offset']}: {len(orders)} orders (total={total}, summary={res.get('summary')!r})")
            if not orders or (total is not None and len(all_orders) >= total): break
            args["offset"] += 10
            await asyncio.sleep(0.5)
        dump("offline_orders_all.json", {"context": ctx, "total": total, "orders": all_orders})
        print(f"\n{len(all_orders)} receipts, {sum(len(o.get('products') or []) for o in all_orders)} line items")

asyncio.run(main())

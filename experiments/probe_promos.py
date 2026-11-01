# /// script
# requires-python = ">=3.12"
# dependencies = ["silpo-py-mcp"]
# ///
"""What's on promo at MY stores right now, matched against my purchase habits.
Run: uv run experiments/probe_promos.py | tee probe-output/promos.txt
"""
import asyncio, json, collections
from datetime import datetime, timedelta, timezone
from pathlib import Path
from silpo_py_mcp import SilpoClient

OUT = Path(__file__).resolve().parent.parent / "probe-output"
hist = json.load(open(OUT / "offline_history.json"))["orders"]
fc = json.load(open(OUT / "forecast.json"))
home = collections.Counter(str(int(r["filId"])) for r in hist).most_common(2)
by_lager = {}
for p in fc["products"]:
    for lid in p["lagerIds"]: by_lager[lid] = p

async def main():
    async with SilpoClient.for_real_server() as c:
        # 1. find my branches
        branches, off = [], 0
        while True:
            r = await c.call_tool("silpo_list_branches", {"limit": 50, "offset": off})
            branches += r.get("branches") or []
            if len(branches) >= r.get("meta", {}).get("total", 0) or not r.get("branches"): break
            off += 50
        mine = [b for b in branches if b.get("externalId") in dict(home)]
        print(f"{len(branches)} branches; mine: {[(b['externalId'], b['address']) for b in mine]}")
        (OUT / "branches_all.json").write_text(json.dumps(branches, ensure_ascii=False, indent=1))
        if not mine: print("!! could not map filId -> branch; falling back to first pickup branch"); mine = [branches[0]]

        report = {}
        for b in mine[:1]:   # one store is enough for the probe
            bid = b["branchId"]
            # 2. real timeslot (so stock is meaningful)
            try:
                ts = await c.call_tool("silpo_get_time_slots", {"branchId": bid, "deliveryType": "SelfPickup"})
                (OUT / "time_slots.json").write_text(json.dumps(ts, ensure_ascii=False, indent=1))
                def find_slot(o):
                    if isinstance(o, dict):
                        if "start" in o and "end" in o: return o
                        for v in o.values():
                            s = find_slot(v)
                            if s: return s
                    if isinstance(o, list):
                        for v in o:
                            s = find_slot(v)
                            if s: return s
                slot = find_slot(ts) or {}
                ctx = {"branchId": bid, "deliveryType": "SelfPickup", "timeslotStart": slot.get("start"), "timeslotEnd": slot.get("end")}
            except Exception as e:
                print("time_slots failed:", e); ctx = None
            if not ctx or not ctx["timeslotStart"]:
                st = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
                ctx = {"branchId": bid, "deliveryType": "SelfPickup", "timeslotStart": st.isoformat(), "timeslotEnd": (st + timedelta(hours=2)).isoformat()}
            print("ctx:", ctx)
            # 3. promotions
            promos = await c.call_tool("silpo_get_promotions", ctx)
            (OUT / "promotions.json").write_text(json.dumps(promos, ensure_ascii=False, indent=1))
            plist = promos.get("promotions") or []
            print(f"\n{len(plist)} promotions at {b['address']}:")
            for p in plist: print(f"  {p['code']:30s} {p['productCount']:5.0f}  {p['title']}")
            # 4. all promo products (paginate), capped
            products, off, page = [], 0, 0
            while True:
                r = await c.call_tool("silpo_get_products", dict(ctx, mustHavePromotion=True, inStock=True, limit=100, offset=off))
                items = r.get("products") or []; products += items; page += 1
                total = (r.get("meta") or {}).get("total")
                if page == 1: print(f"\npromo products in stock: total={total}, page size={len(items)}, keys={list(items[0].keys()) if items else None}")
                if not items or (total and len(products) >= total) or page >= 40: break
                off += len(items); await asyncio.sleep(0.3)
            (OUT / "promo_products.json").write_text(json.dumps(products, ensure_ascii=False, indent=1))
            # 5. match to habits
            hits = []
            for pr in products:
                lid = pr.get("externalProductId")
                if lid and int(lid) in by_lager:
                    h = by_lager[int(lid)]
                    disc = round((1 - pr["price"] / pr["oldPrice"]) * 100) if pr.get("oldPrice") else None
                    hits.append((h["status"], h["buys"], disc, pr["price"], pr.get("oldPrice"), pr.get("specialPrices"), h["name"], h.get("due_in")))
            order = {"overdue": 0, "due": 1, "soon": 2, "stocked": 3, "irregular": 4, "lapsed": 5, "occasional": 6}
            hits.sort(key=lambda h: (order[h[0]], -h[1]))
            print(f"\n{len(hits)} promo products match something you've bought ({len(products)} promo products scanned):")
            print(f"{'status':10s} {'buys':>4} {'disc':>5} {'price':>7} {'old':>7}  due   name")
            for h in hits: print(f"{h[0]:10s} {h[1]:4d} {str(h[2])+'%' if h[2] else '-':>5} {h[3]:7.2f} {str(h[4] or '-'):>7}  {str(h[7]) if h[7] is not None else '-':>4}  {h[6][:55]}" + (f"  special={h[5]}" if h[5] else ""))
        print("\nalso: personal promos / coupons")
        for n in ("silpo_get_my_promos", "silpo_get_my_coupons", "silpo_get_promo_codes"):
            try:
                r = await c.call_tool(n, {}); (OUT / f"{n.replace('silpo_get_','')}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1)); print(f"  {n}: {r.get('summary')}")
            except Exception as e: print(f"  {n}: !! {e}")
asyncio.run(main())

"""Purchase-cadence forecast and household habits. Pure Python, no HA imports.

Input: list of receipts as returned by silpo_get_my_offline_orders (dicts).
Output: dict(products=[...], habits={...}) — JSON-serialisable.
"""
from __future__ import annotations

import re
import statistics as st
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

MIN_BUYS = 3          # fewer -> "occasional"
RATE_MIN_BUYS = 6     # bursty but frequent -> rate model
STABLE_CV = 0.6       # MAD/median gap threshold for the gap model
LONG_CYCLE_DAYS = 60  # gaps longer than this are not actionable day-to-day

_UNIT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(кг|г|л|мл|шт)", re.I)
_MULTI = re.compile(r"(\d+)\s*[\*хx]\s*(\d+(?:[.,]\d+)?)\s*(кг|г|л|мл|шт)", re.I)
_SCALE = {"кг": (1000, "g"), "г": (1, "g"), "л": (1000, "ml"), "мл": (1, "ml"), "шт": (1, "pc")}


def receipt_key(r: dict) -> str:
    """Stable identity for a receipt (API exposes no receipt id)."""
    return f"{r['createdAt']}|{int(r['filId'])}|{r['sumReg']}"


def parse_unit(unit: str) -> tuple[float | None, str | None]:
    """'0,33л' -> (330, 'ml'); '3*22г/уп' -> (66, 'g'); 'кг' -> (1000, 'g') (quantity is kg)."""
    u = (unit or "").replace(",", ".")
    if u.strip().lower() == "кг":
        return 1000.0, "g"
    m = _MULTI.search(u)
    if m:
        n, a, b = int(m.group(1)), float(m.group(2)), m.group(3).lower()
    else:
        m = _UNIT.search(u)
        if not m:
            return None, None
        n, a, b = 1, float(m.group(1)), m.group(2).lower()
    k, base = _SCALE[b]
    return n * a * k, base


def _median(xs):
    return st.median(xs) if xs else 0


def analyze_products(receipts: list[dict], asof: date) -> list[dict[str, Any]]:
    buys: dict[int, list] = defaultdict(list)   # lagerId -> [(day, qty, amount, base, price, name)]
    for r in receipts:
        day = date.fromisoformat(r["createdAt"][:10])
        for p in r.get("products") or []:
            amt, base = parse_unit(p.get("unit") or "")
            q = float(p.get("quantity") or 0)
            buys[int(p["lagerId"])].append((day, q, amt * q if amt else None, base, float(p.get("price") or 0), p["name"], p.get("unit")))

    out = []
    for lid, b in buys.items():
        days = sorted({x[0] for x in b})
        n = len(days)
        name = Counter(x[5] for x in b).most_common(1)[0][0]
        base = next((x[3] for x in b if x[3]), None)
        amts = [x[2] for x in b if x[2]]
        per_buy = _median([sum(x[2] for x in b if x[0] == d and x[2]) for d in days]) if amts else None
        last, first = days[-1], days[0]
        since = (asof - last).days
        row: dict[str, Any] = {
            "lager_id": lid, "name": name, "unit": b[-1][6], "buys": n, "first": first.isoformat(), "last": last.isoformat(),
            "days_since": since, "spent": round(sum(x[4] * x[1] for x in b), 2), "last_price": b[-1][4],
            "qty_per_buy": _median(list(Counter(x[0] for x in b).values())),
            "amount_per_buy": round(per_buy) if per_buy else None, "base": base,
            "model": None, "gap": None, "gap_mad": None, "due_in": None, "status": "occasional", "rate_per_week": None,
        }
        if n >= MIN_BUYS:
            gaps = [(y - x).days for x, y in zip(days, days[1:])]
            med = _median(gaps)
            mad = _median([abs(g - med) for g in gaps])
            mean = ((last - first).days) / (n - 1)
            cv = (mad / med) if med else 9.0
            span_w = max((last - first).days, 7) / 7
            row["rate_per_week"] = round(sum(amts) / span_w) if amts else None
            if cv <= STABLE_CV:
                row.update(model="gap", gap=med, gap_mad=mad)
                gap, tol = med, max(2, mad)
            elif n >= RATE_MIN_BUYS:
                row.update(model="rate", gap=round(mean, 1), gap_mad=round(mad, 1))
                gap, tol = mean, max(3, mean * 0.5)
            else:
                row.update(model=None, gap=med, gap_mad=mad, status="irregular")
                gap = None
            if gap:
                row["due_in"] = round(gap - since)
                if since > 2 * gap and since > 21:
                    row["status"] = "lapsed"
                elif gap > LONG_CYCLE_DAYS:
                    row["status"] = "long_cycle"
                elif since > gap + tol:
                    row["status"] = "overdue"
                elif gap - since <= 2:
                    row["status"] = "due"
                elif gap - since <= 7:
                    row["status"] = "soon"
                else:
                    row["status"] = "stocked"
            elif since > 90:
                row["status"] = "lapsed"
        out.append(row)
    order = {"overdue": 0, "due": 1, "soon": 2, "stocked": 3, "long_cycle": 4, "irregular": 5, "lapsed": 6, "occasional": 7}
    out.sort(key=lambda r: (order[r["status"]], r["due_in"] if r["due_in"] is not None else 0, -r["buys"]))
    return out


def analyze_habits(receipts: list[dict], asof: date) -> dict[str, Any]:
    if not receipts:
        return {"receipts": 0}
    wk: dict[date, dict] = defaultdict(lambda: {"spend": 0.0, "discount": 0.0, "bonus": 0.0, "trips": 0, "items": 0})
    weekday, hours, stores, month = Counter(), Counter(), Counter(), defaultdict(float)
    for r in receipts:
        d = datetime.fromisoformat(r["createdAt"])
        k = d.date() - timedelta(days=d.weekday())
        w = wk[k]
        w["spend"] += r["sumReg"]; w["discount"] += r.get("sumDiscount") or 0; w["bonus"] += r.get("accruedBalaBonusesSum") or 0
        w["trips"] += 1; w["items"] += len(r.get("products") or [])
        weekday[d.strftime("%a")] += 1; hours[d.hour] += 1; stores[r.get("filialName") or str(r.get("filId"))] += 1
        month[r["createdAt"][:7]] += r["sumReg"]
    this_monday = asof - timedelta(days=asof.weekday())
    def week(k):
        return wk.get(k, {"spend": 0.0, "discount": 0.0, "bonus": 0.0, "trips": 0, "items": 0})
    last_week = week(this_monday - timedelta(days=7))
    cur_week = week(this_monday)
    last4 = [week(this_monday - timedelta(days=7 * i)) for i in range(1, 5)]
    prev4 = [week(this_monday - timedelta(days=7 * i)) for i in range(5, 9)]
    avg4 = st.mean(w["spend"] for w in last4); avgp = st.mean(w["spend"] for w in prev4)
    spend = sum(r["sumReg"] for r in receipts); disc = sum(r.get("sumDiscount") or 0 for r in receipts)
    first = min(r["createdAt"][:10] for r in receipts); last = max(r["createdAt"][:10] for r in receipts)
    weeks = max(len(wk), 1)
    return {
        "receipts": len(receipts), "first_receipt": first, "last_receipt": last, "weeks": weeks,
        "spend_total": round(spend), "discount_total": round(disc), "discount_pct": round(disc / (spend + disc) * 100, 1) if spend else 0,
        "bonus_total": round(sum(r.get("accruedBalaBonusesSum") or 0 for r in receipts), 2),
        "trips_per_week": round(len(receipts) / weeks, 1), "avg_basket": round(spend / len(receipts)),
        "avg_items_per_trip": round(sum(len(r.get("products") or []) for r in receipts) / len(receipts), 1),
        "current_week": {k: round(v, 2) for k, v in cur_week.items()},
        "last_week": {k: round(v, 2) for k, v in last_week.items()},
        "avg_week_spend_4w": round(avg4), "avg_week_spend_prev_4w": round(avgp),
        "trend_4w_pct": round((avg4 / avgp - 1) * 100) if avgp else 0,
        "weekday": dict(weekday.most_common()), "hours": {str(k): v for k, v in sorted(hours.items())},
        "stores": dict(stores.most_common(5)), "monthly": {k: round(v) for k, v in sorted(month.items())},
        "weekly": [{"week": (this_monday - timedelta(days=7 * i)).isoformat(), **{k: round(v, 2) for k, v in week(this_monday - timedelta(days=7 * i)).items()}} for i in range(12, 0, -1)],
    }


def analyze(receipts: list[dict], asof: date | None = None) -> dict[str, Any]:
    asof = asof or date.today()
    products = analyze_products(receipts, asof)
    counts = Counter(p["status"] for p in products)
    return {"asof": asof.isoformat(), "products": products, "status_counts": dict(counts), "habits": analyze_habits(receipts, asof)}

#!/usr/bin/env python3
"""Purchase-cadence forecast + household habits from probe-output/offline_history.json (stdlib only).
Usage: python3 experiments/cadence.py [--asof YYYY-MM-DD]  → probe-output/forecast.md + forecast.json
"""
import json, re, sys, statistics as st, collections
from datetime import datetime, date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, OUT_MD, OUT_JSON = ROOT/"probe-output/offline_history.json", ROOT/"probe-output/forecast.md", ROOT/"probe-output/forecast.json"
ASOF = date.fromisoformat(sys.argv[sys.argv.index("--asof")+1]) if "--asof" in sys.argv else date.today()
MIN_BUYS, STABLE_CV = 3, 0.6

# ---------- unit parsing ----------
UNIT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(кг|г|л|мл|шт)", re.I)
MULTI_RE = re.compile(r"(\d+)\s*[\*хx]\s*(\d+(?:[.,]\d+)?)\s*(кг|г|л|мл|шт)", re.I)
def parse_unit(u: str):
    """-> (amount, base) where base in g|ml|pc, or (None, None)."""
    u = u.replace(",", ".")
    if u.strip().lower() == "кг": return 1000.0, "g"       # weighed: quantity is kg
    m = MULTI_RE.search(u)
    if m: n, a, b = int(m.group(1)), float(m.group(2)), m.group(3).lower()
    else:
        m = UNIT_RE.search(u)
        if not m: return None, None
        n, a, b = 1, float(m.group(1)), m.group(2).lower()
    scale = {"кг": (1000, "g"), "г": (1, "g"), "л": (1000, "ml"), "мл": (1, "ml"), "шт": (1, "pc")}[b]
    return n * a * scale[0], scale[1]

# ---------- canonical key: same product under different lagerIds ----------
def canon(name: str):
    toks = re.findall(r"[а-яіїєґa-z0-9%]+", name.lower())
    return " ".join(sorted(toks))

def main():
    data = json.load(open(SRC)); receipts = data["orders"]
    prods = collections.defaultdict(list)       # canon -> [(day, qty, amount, base, price, name, lagerId)]
    for r in receipts:
        day = date.fromisoformat(r["createdAt"][:10])
        for p in r["products"]:
            amt, base = parse_unit(p["unit"])
            q = p["quantity"]
            prods[canon(p["name"])].append((day, q, (amt*q if amt else None), base, p["price"], p["name"], int(p["lagerId"])))

    rows = []
    for key, buys in prods.items():
        days = sorted({b[0] for b in buys})
        n = len(days); name = max((b[5] for b in buys), key=len); ids = sorted({b[6] for b in buys})
        qty_per_buy = st.median(collections.Counter(b[0] for b in buys).values()) if n else 0
        amts = [b[2] for b in buys if b[2]]; base = next((b[3] for b in buys if b[3]), None)
        per_buy = st.median([sum(b[2] for b in buys if b[0]==d and b[2]) for d in days]) if amts else None
        spent = sum(b[4]*b[1] for b in buys)
        last = days[-1]; since = (ASOF - last).days
        row = dict(name=name, lagerIds=ids, buys=n, first=str(days[0]), last=str(last), since=since, spent=round(spent),
                   qty_per_buy=qty_per_buy, amount_per_buy=(round(per_buy) if per_buy else None), base=base)
        if n < MIN_BUYS:
            row.update(status="occasional", median_gap=None)
        else:
            gaps = [(b-a).days for a, b in zip(days, days[1:])]
            med = st.median(gaps); mad = st.median([abs(g-med) for g in gaps]); cv = mad/med if med else 9
            span = (days[-1]-days[0]).days or 1
            rate = (sum(amts)/span*7) if amts else None     # per week
            row.update(median_gap=med, mad=mad, cv=round(cv,2), due_in=round(med-since), rate_per_week=(round(rate) if rate else None))
            if since > max(3*med, 30): row["status"] = "lapsed"
            elif cv > STABLE_CV: row["status"] = "irregular"
            elif since > med + max(2, mad): row["status"] = "overdue"
            elif med - since <= 2: row["status"] = "due"
            elif med - since <= 7: row["status"] = "soon"
            else: row["status"] = "stocked"
        rows.append(row)

    # ---------- habits ----------
    wk = collections.defaultdict(lambda: dict(spend=0.0, disc=0.0, bonus=0.0, trips=0, items=0))
    weekday = collections.Counter(); store = collections.Counter(); hours = collections.Counter()
    for r in receipts:
        d = datetime.fromisoformat(r["createdAt"]); k = d.date() - timedelta(days=d.weekday())
        w = wk[k]; w["spend"] += r["sumReg"]; w["disc"] += r["sumDiscount"]; w["bonus"] += r["accruedBalaBonusesSum"]; w["trips"] += 1; w["items"] += len(r["products"])
        weekday[d.strftime("%a")] += 1; store[r["filialName"]] += 1; hours[d.hour] += 1
    weeks = sorted(wk.items())
    last12 = weeks[-13:-1] if len(weeks) > 13 else weeks
    base12 = [w["spend"] for _, w in weeks[-27:-14]] if len(weeks) > 27 else [w["spend"] for _, w in weeks[:-13]]
    recent = st.mean([w["spend"] for _, w in last12]); baseline = st.mean(base12) if base12 else recent
    month = collections.defaultdict(float)
    for r in receipts: month[r["createdAt"][:7]] += r["sumReg"]
    top_spend = sorted(rows, key=lambda r: -r["spent"])[:15]
    habits = dict(asof=str(ASOF), receipts=len(receipts), weeks=len(weeks),
                  spend_total=round(sum(r["sumReg"] for r in receipts)), discount_total=round(sum(r["sumDiscount"] for r in receipts)),
                  bonus_total=round(sum(r["accruedBalaBonusesSum"] for r in receipts)),
                  avg_week_spend_recent12=round(recent), avg_week_spend_prev13=round(baseline), trend_pct=round((recent/baseline-1)*100) if baseline else 0,
                  trips_per_week=round(len(receipts)/len(weeks), 1), avg_basket=round(st.mean([r["sumReg"] for r in receipts])),
                  avg_items_per_trip=round(st.mean([len(r["products"]) for r in receipts]), 1),
                  weekday=dict(weekday.most_common()), hours=dict(sorted(hours.items())), stores=dict(store.most_common(3)),
                  monthly=dict(sorted(month.items())), weekly_last12=[(str(k), round(w["spend"]), w["trips"]) for k, w in last12])

    # ---------- output ----------
    order = ["overdue", "due", "soon", "stocked", "irregular", "lapsed", "occasional"]
    by = {s: sorted([r for r in rows if r["status"] == s], key=lambda r: (r.get("due_in") if r.get("due_in") is not None else 0, -r["buys"])) for s in order}
    L = [f"# Forecast as of {ASOF}", "", f"Articles: {len(rows)} canonical products from {sum(len(r['lagerIds']) for r in rows)} lagerIds. "
         + ", ".join(f"{s}: {len(by[s])}" for s in order), ""]
    def fmt(r):
        amt = f"{r['amount_per_buy']}{r['base']}" if r.get("amount_per_buy") else f"{r['qty_per_buy']:g}×"
        rate = f", ~{r['rate_per_week']}{r['base']}/wk" if r.get("rate_per_week") else ""
        return f"| {r['name'][:48]} | {r['buys']} | {r['median_gap']:g}±{r['mad']:g} | {r['since']} | {r['due_in']:+d} | {amt}{rate} |"
    for s in ["overdue", "due", "soon", "stocked"]:
        L += [f"## {s.upper()} ({len(by[s])})", "", "| product | buys | gap (d) | since | due in | per buy |", "|---|---|---|---|---|---|"] + [fmt(r) for r in by[s]] + [""]
    L += [f"## IRREGULAR ({len(by['irregular'])}) — bought ≥{MIN_BUYS}×, no stable rhythm", ""] + [f"- {r['name'][:60]} — {r['buys']}×, gap {r['median_gap']:g}±{r['mad']:g}d, last {r['since']}d ago" for r in by["irregular"][:30]] + [""]
    L += [f"## LAPSED ({len(by['lapsed'])}) — used to be regular, stopped", ""] + [f"- {r['name'][:60]} — {r['buys']}×, was every {r['median_gap']:g}d, last {r['since']}d ago" for r in by["lapsed"][:30]] + [""]
    h = habits
    L += ["# Household habits", "", f"- {h['receipts']} receipts over {h['weeks']} weeks → {h['trips_per_week']} trips/week, avg basket {h['avg_basket']} UAH, {h['avg_items_per_trip']} items/trip",
          f"- Spent {h['spend_total']} UAH; discounts {h['discount_total']} ({round(h['discount_total']/(h['spend_total']+h['discount_total'])*100)}% off gross); bonuses earned {h['bonus_total']}",
          f"- Weekly spend: last 12 wks avg {h['avg_week_spend_recent12']} vs previous 13 wks {h['avg_week_spend_prev13']} → {h['trend_pct']:+d}%",
          f"- Weekday rhythm: " + ", ".join(f"{k} {v}" for k, v in h["weekday"].items()),
          f"- Hour of day (top): " + ", ".join(f"{k}:00 ×{v}" for k, v in sorted(h["hours"].items(), key=lambda x: -x[1])[:5]),
          f"- Stores: " + "; ".join(f"{k[:35]} ×{v}" for k, v in h["stores"].items()), "",
          "## Monthly spend", "", "| month | UAH |", "|---|---|"] + [f"| {k} | {round(v)} |" for k, v in h["monthly"].items()] + ["",
          "## Top 15 products by spend (12 mo)", "", "| product | spent | buys | status |", "|---|---|---|---|"] + [f"| {r['name'][:48]} | {r['spent']} | {r['buys']} | {r['status']} |" for r in top_spend]
    OUT_MD.write_text("\n".join(L)); OUT_JSON.write_text(json.dumps(dict(asof=str(ASOF), products=rows, habits=habits), ensure_ascii=False, indent=1))
    print("\n".join(L[:3])); print(f"wrote {OUT_MD.name}, {OUT_JSON.name}")

main()

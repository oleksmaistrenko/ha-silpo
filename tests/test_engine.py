"""Run: python3 -m pytest tests/  (or python3 tests/test_engine.py) — uses probe-output/offline_history.json if present."""
import json, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "silpo"))
from engine import analyze, parse_unit, receipt_key  # noqa: E402

FIX = Path(__file__).resolve().parent.parent / "probe-output" / "offline_history.json"

def test_parse_unit():
    assert parse_unit("0,33л") == (330.0, "ml")
    assert parse_unit("3*22г/уп") == (66.0, "g")
    assert parse_unit("кг") == (1000.0, "g")
    assert parse_unit("10шт") == (10.0, "pc")
    assert parse_unit("1,25л") == (1250.0, "ml")
    assert parse_unit("шт") == (None, None)

def test_synthetic():
    rc = [{"createdAt": f"2026-10-{d:02d}T10:00:00", "filId": 1, "sumReg": 10, "sumDiscount": 0, "accruedBalaBonusesSum": 0,
           "products": [{"lagerId": 7, "name": "Milk", "unit": "0,9л", "quantity": 1, "price": 50}]} for d in (1, 6, 11, 16, 21)]
    res = analyze(rc, date(2026, 10, 27))
    p = res["products"][0]
    assert p["model"] == "gap" and p["gap"] == 5 and p["status"] == "due" and p["due_in"] == -1
    assert len({receipt_key(r) for r in rc}) == 5

def test_fixture():
    if not FIX.exists():
        return
    rc = json.load(open(FIX))["orders"]
    res = analyze(rc, date(2026, 10, 29))
    sc = res["status_counts"]; print(sc)
    assert sc.get("due", 0) + sc.get("overdue", 0) + sc.get("soon", 0) > 5
    assert res["habits"]["receipts"] == len(rc)
    for s in ("overdue", "due", "soon"):
        for p in [x for x in res["products"] if x["status"] == s][:6]:
            print(f"  {s:8s} {p['model']:4s} {p['buys']:3d} gap={p['gap']} since={p['days_since']} due={p['due_in']:+d} {p['name'][:50]}")
    rate = [p for p in res["products"] if p["model"] == "rate"]; print("rate-model products:", len(rate), [p["name"][:30] for p in rate[:6]])

if __name__ == "__main__":
    test_parse_unit(); test_synthetic(); test_fixture(); print("ok")

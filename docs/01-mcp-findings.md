# Silpo MCP — probe findings (2026-10-29)

Endpoint `https://mcp.silpo.ua/mcp`, OAuth 2.1 + PKCE, 42 tools live (docs say 40).
Client used: `silpo-py-mcp` (PyPI), token cached encrypted in `~/.silpo_py_mcp`, refresh is automatic.

## Data source: `silpo_get_my_offline_orders`
- Online orders: none for this account → in-store receipts are the only stream.
- Requires cart context (`branchId`, `deliveryType`, `timeslotStart/End`). A real cart is NOT needed:
  any branch from `silpo_list_branches(hasPickup=true)` + `SelfPickup` + a synthetic future timeslot works.
  The context only drives the `catalogProduct` availability enrichment.
- Pagination: `limit` ≤ 10, `offset`. `dateStart`/`dateEnd` ISO, default window = last 6 months.
- **History depth: rolling 12 months** (first receipt 2025-10-29 on 2026-10-29). Windows earlier than that
  return a bogus `total=20` with no in-window orders. ⇒ the integration must persist every receipt locally.
- `createdAt` has no tz offset (local store time, roughly).

### Receipt fields
`filId`, `filialName`, `cityName`, `createdAt`, `sumReg`, `sumDiscount`, `accruedBalaBonusesSum`,
`receiptUrl`, `rewards[]` (applied promos), `chequeMagicName`/`chequePrediction` (fluff),
`products[]`: `lagerId` (stable article id), `name`, `unit` (pack size string, or `кг` for weighed),
`quantity`, `price`, `image`, `catalogProduct` (live catalog link or null).

Dedupe key for receipts: (`createdAt`, `filId`, `sumReg`) — no receipt id is exposed.

## Account snapshot (12 months)
- 263 receipts, ~22/month, 1857 line items, 907 distinct articles. Two home stores (129 / 128 receipts).
- Spend ≈ 198k UAH, discounts ≈ 23k, bonuses earned ≈ 2.2k.
- Repeat structure: 609 articles bought once, 135 twice, 67 ×3, 96 articles with ≥4 buys.
- Of the 96, 49 have a stable cadence (MAD ≤ 0.6 × median gap) → forecastable today.
  Examples: oranges every ~4.5d, cherry tomatoes ~8d, bananas ~13d, cottage cheese ~13.5d,
  herring salad ~14d, Jaffa nectars ~7–10d, baguette ~8d.
- Family: 2 members on the loyalty account; unknown yet whether partner's receipts are in this stream.

## Implications for the design
1. Local store (SQLite) of receipts + line items; daily incremental pull of the last ~14 days, dedupe.
2. Cadence per `lagerId`, with a canonical-product layer on top (Морква Моркішка appears under 2 ids;
   Jaffa flavors could be one "juice" bucket). LLM-assisted mapping once, cached.
3. Forecast only for ≥3–4 buys and stable gap; everything else is "occasional".
4. Unit parser for `unit` strings (г/кг/мл/л/шт, multipacks `3*22г/уп`) to get consumption rates.
5. Household habits = spend/discount/bonus per week, category mix, store split, weekday rhythm.

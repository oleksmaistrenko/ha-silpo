<p align="center"><img src="brand/icon.png" width="96" alt=""></p>

<h1 align="center">Silpo purchases for Home Assistant</h1>

<p align="center">
Pantry forecast and household habits from your in-store Silpo receipts — no manual inventory.<br>
<em>Прогноз покупок і звички домогосподарства з чеків «Сільпо» — без ручного обліку.</em>
</p>

<p align="center">
<a href="https://github.com/oleksmaistrenko/ha-silpo/releases"><img src="https://img.shields.io/github/v/release/oleksmaistrenko/ha-silpo?style=flat-square" alt="release"></a>
<img src="https://img.shields.io/badge/HA-2026.11%2B%20Marketplace%20%7C%20HACS-41bdf5?style=flat-square" alt="ha">
<img src="https://img.shields.io/github/license/oleksmaistrenko/ha-silpo?style=flat-square" alt="license">
</p>

---

Every time you scan your Власний Рахунок card at a Silpo checkout, the receipt lands in your account. This
integration reads those receipts through the **official Silpo MCP**, learns how often you buy each article,
and tells you what is due — plus what the receipts say about the household: spend, rhythm, discounts, bonuses,
and which current promos actually match what you buy.

Nothing to type in. No barcode scanning. No consumption logging.

## Features

| | |
|---|---|
| 🛒 **Needed soon** | Per-article forecast: `overdue · due · soon · stocked`, with the usual interval, last purchase and pack size. Items that were regular and stopped show as *lapsed*. |
| 📈 **Habits** | Weekly and monthly spend, trips per week, average basket, weekday and hour rhythm, discount share, bonuses earned, store split. Plain numeric sensors feed HA's long-term statistics. |
| 🏷️ **Promos that fit you** | Current in-store promotions at your two most-visited stores, intersected with the articles you regularly buy. Fires an event per new match for notifications. |
| 🎟️ **Personal offers & coupons** | Your selectable balabonus offers and coupons, with their on/off state, so you notice the ones worth activating. |
| 🔐 **Official API, OAuth 2.1** | Logs in with your Silpo account through the standard Home Assistant OAuth flow (PKCE). Tokens refresh automatically; a re-auth prompt appears if the session expires. |
| 💾 **Keeps history** | Silpo keeps ~12 months of receipts; the integration stores every receipt it has seen, so your history keeps growing. |

## Installation

### Marketplace (Home Assistant 2026.11+) or HACS
1. **Settings → Marketplace → Add from link** (HACS: *Custom repositories*), enter `oleksmaistrenko/ha-silpo`, type *Integration*.
2. Download **Silpo purchases**, restart Home Assistant.

### Manual
Copy `custom_components/silpo` into `<config>/custom_components/` and restart. From the HA Terminal add-on:
```sh
cd /homeassistant
wget -O /tmp/silpo.zip https://github.com/oleksmaistrenko/ha-silpo/archive/refs/heads/main.zip
unzip -o /tmp/silpo.zip -d /tmp/ && cp -r /tmp/ha-silpo-main/custom_components/silpo custom_components/
```

### Set up
**Settings → Devices & services → Add integration → Silpo purchases.** A Silpo login page opens: phone number,
SMS code, approve access. The first refresh backfills a year of receipts (about a minute).

## Entities

| Entity | State | Attributes |
|---|---|---|
| `sensor.silpo_needed_soon` | overdue + due + soon count | `overdue`, `due`, `soon`, `stocked`, `lapsed` (lists of products), `shopping_list` (names), `counts` |
| `sensor.silpo_habits` | trips per week | spend / discount / bonus totals, `current_week`, `last_week`, 4-week trend, `weekday`, `hours`, `stores`, `monthly`, `weekly` (12 rows), `sync` |
| `sensor.silpo_promo_matches` | promo products among your regulars | `regular`, `matches`, `promotions` (per store), `personal_promos`, `coupons` |
| `sensor.silpo_this_week_spend` · `_last_week_spend` · `_this_week_trips` · `_average_weekly_spend_4w` · `_discount_share` · `_bonuses_earned` · `_stored_receipts` | numbers for graphs and statistics | |
| `binary_sensor.silpo_connected` | authenticated and last sync succeeded | |

Each product entry carries: `lager_id`, `name`, `unit`, `status`, `model` (`gap`/`rate`), `buys`, `gap` (days), `days_since`,
`due_in`, `qty_per_buy`, `amount_per_buy` + `base` (`g`/`ml`/`pc`), `rate_per_week`, `last`, `last_price`.

**Event** `silpo_promo_match` — fired once per newly discounted product you buy regularly; payload is the match
(`name`, `price`, `old_price`, `discount_pct`, `status`, `due_in`, `gap`, `branch`).

## Dashboard

A ready three-tab dashboard (Shopping · Habits · Offers) is in [`examples/dashboard.yaml`](examples/dashboard.yaml) —
create an empty dashboard, open the raw configuration editor and paste it in. Everything is core cards.

Notify on a matching promo:
```yaml
triggers:
  - trigger: event
    event_type: silpo_promo_match
actions:
  - action: notify.mobile_app_phone
    data:
      title: "Silpo: {{ trigger.event.data.name }}"
      message: "−{{ trigger.event.data.discount_pct }}% ({{ trigger.event.data.price }} ₴) — you buy it every ~{{ trigger.event.data.gap }} days"
```

## How the forecast works

- Receipts are fetched every 6 hours (last 21 days, deduplicated) and merged into `.storage/silpo.receipts.<entry>`.
- Each article (`lagerId`) with **3+ purchases** gets a model:
  - **gap** — intervals are regular (median absolute deviation ≤ 60 % of the median): due when the median interval has passed;
  - **rate** — frequent but bursty (6+ purchases): due when the average interval has passed, with wider tolerance.
- `overdue` beyond the interval + tolerance; `lapsed` beyond 2× the interval (product switch, season over);
  `long_cycle` for intervals over 60 days; `irregular` when no model fits; `occasional` for 1–2 purchases.
- Promotions are checked once a day at the two stores where you shop most, matched on the article id — no fuzzy names.

## Privacy

Your receipts stay in your Home Assistant. The integration talks only to `mcp.silpo.ua`, acting as you after you log in;
the Silpo session token is never exposed to it (Silpo's design). No third-party services, no telemetry.

## Limitations & roadmap

- v0.1 is keyed on exact articles: flavour and brand variants are separate products, and a few non-food regulars may
  appear in *needed soon*. Planned: product families, category tags, seasonality, an ignore list.
- Only in-store receipts are used (online orders are available from the API and easy to add).
- Personal offers are shown but not matched to your products yet (free-text descriptions).
- No tool exists in the MCP to activate an offer — the integration can tell you, you tap it in the app.

## Development

```
python3 tests/test_engine.py                      # engine tests against your own dump
uv run experiments/probe.py                       # dump tools/list + first API calls (opens Silpo login)
uv run experiments/probe_backfill.py              # full receipt history -> probe-output/offline_history.json
python3 experiments/cadence.py                    # standalone forecast + habits report
```
`probe-output/` is git-ignored — it holds your personal data. Findings about the API are in [`docs/`](docs/).

Not affiliated with Silpo / Fozzy Group. Uses the public [Silpo MCP](https://ai-factory.silpo.ua/docs/mcp) under its terms.

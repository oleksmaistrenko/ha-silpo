# ha-silpo — Silpo purchases for Home Assistant

Pantry forecast and household habits from your in-store Silpo receipts, via the official
[Silpo MCP](https://ai-factory.silpo.ua/docs/mcp). No manual inventory: the integration learns
how often you buy each article and tells you what is due.

**v0.1 — no LLM.** Everything is keyed on the receipt article id (`lagerId`).

## What you get
| Entity | State | Attributes |
|---|---|---|
| `sensor.silpo_needed_soon` | number of overdue + due + soon products | `overdue`, `due`, `soon`, `stocked`, `lapsed` lists; `shopping_list` (names); `counts` |
| `sensor.silpo_habits` | trips per week | spend/discount/bonus totals, weekday & hour rhythm, stores, `monthly`, last 12 `weekly` rows, `current_week`, `last_week`, 4-week trend |
| `sensor.silpo_promo_matches` | number of promo products you regularly buy | `matches` (with discount %, status, due_in), `promotions` per store, `personal_promos`, `coupons` |
| `sensor.silpo_this_week_spend`, `…_last_week_spend`, `…_this_week_trips`, `…_average_weekly_spend_4w`, `…_discount_share`, `…_bonuses_earned`, `…_stored_receipts` | plain numbers for history graphs | |
| `binary_sensor.silpo_connected` | auth + last sync OK | |

Event `silpo_promo_match` fires once per newly discounted product you buy regularly (payload = the match).

## How it works
- Every 6 h: pull receipts from the last 21 days, merge into a local store (`.storage/silpo.receipts.*`).
  First run backfills the full ~12 months the API keeps. Receipts are never deleted, so history grows past the API window.
- Forecast per article: *gap model* for steady items (median interval, MAD ≤ 60 %), *rate model* for
  frequent-but-bursty items (≥ 6 buys), ≥ 3 buys required; statuses `overdue / due / soon / stocked / long_cycle / irregular / lapsed / occasional`.
- Every 24 h: in-stock promo products at your two most-visited stores, intersected with your articles.
- Auth: OAuth 2.1 + PKCE, dynamic client registration, HA's standard `my.home-assistant.io` redirect. Tokens refresh automatically;
  if Silpo drops the session the entry asks to re-authenticate.

## Install
1. Copy `custom_components/silpo` into `<config>/custom_components/` (or add this repo as a custom HACS repository).
2. Restart Home Assistant.
3. Settings → Devices & services → Add integration → **Silpo purchases** → log in with your Silpo phone + SMS code.
4. First refresh backfills a year of receipts (≈ 30 API calls, a minute or so).

## Dashboard example (Markdown card)
```yaml
type: markdown
title: Silpo — needed soon
content: >
  {% set s = state_attr('sensor.silpo_needed_soon','overdue') + state_attr('sensor.silpo_needed_soon','due') + state_attr('sensor.silpo_needed_soon','soon') %}
  {% for p in s %}
  - **{{ p.name }}** — every ~{{ p.gap | round(0) }}d, last {{ p.days_since }}d ago ({{ p.status }})
  {% endfor %}

  {% set m = state_attr('sensor.silpo_promo_matches','matches') %}
  {% if m %}**On promo:** {% for x in m[:5] %}{{ x.name }} −{{ x.discount_pct }}%{{ ", " if not loop.last }}{% endfor %}{% endif %}
```

Notification automation:
```yaml
trigger: {platform: event, event_type: silpo_promo_match}
action:
  service: notify.mobile_app_phone
  data:
    title: "Silpo: {{ trigger.event.data.name }}"
    message: "−{{ trigger.event.data.discount_pct }}% ({{ trigger.event.data.price }} UAH), you buy it every ~{{ trigger.event.data.gap }} days"
```

## Repo layout
- `custom_components/silpo/` — the integration (`engine.py` is pure Python, shared with experiments)
- `experiments/` — MCP probes and the standalone cadence report (`uv run experiments/probe.py` etc.)
- `tests/test_engine.py` — engine tests against `probe-output/offline_history.json`
- `docs/` — findings and design notes; `probe-output/` is git-ignored (personal data)

## Roadmap
Product families (flavor/brand variants), category tagging, seasonality, personal-promo text matching (LLM),
push the due list into a Silpo cart, partner's receipts.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

OLX.pt Car Deal Finder: crawls OLX.pt's public car listings JSON API, stores ads in Supabase, computes
market-median pricing per brand/model/2-year bucket, flags underpriced "flip" candidates, alerts via
Telegram, and shows a Streamlit dashboard. Runs on free tiers (GitHub Actions for the crawler, Streamlit
Community Cloud for the dashboard).

## Commands

```bash
pip install -r requirements.txt
cp .env.example .env                  # fill in SUPABASE_URL/KEY, Telegram token/chat id

python -m src.crawler                 # one incremental crawl
DEEP_SWEEP=1 python -m src.crawler    # full price-bucketed sweep (rebuilds market stats)
streamlit run dashboard/app.py        # dashboard at localhost:8501
```

There is no test suite, linter, or build step in this repo.

Database schema lives in `supabase_schema.sql` — run it manually in the Supabase SQL Editor (no migration
tool). `market_stats` and `deals_view` are SQL views, not tables, so schema changes to the aggregation
logic happen there, not in Python.

## Architecture

Pipeline, run end-to-end by `src/crawler.py::run()` on every invocation:

1. **`src/olx_api.py`** — talks to OLX's public JSON API directly (`olx.pt/api/v1/offers/`), no browser
   rendering. `parse_offer()` flattens OLX's raw offer JSON into the `ads` row shape. OLX's API caps
   `offset` at 1000, so `fetch_deep_sweep()` walks fixed price buckets (`SWEEP_BUCKETS`) to cover the full
   catalog for the weekly deep sweep; the incremental crawl just pages newest-first until it hits ads
   already in the DB. OLX's category params never expose brand directly — `guess_brand()` regex-matches it
   out of the free-text title instead. If this file needs changing, it's almost always because OLX changed
   their API/HTML.
2. **`src/db.py`** — thin Supabase wrapper (upsert ads in batches of 500, read market stats paginated in
   chunks of 1000, track which deals were already inserted/notified). All Supabase access goes through
   `client()`, a lazily-initialized singleton.
3. **`src/deal_engine.py`** — pure logic, no I/O. `is_blacklisted()` checks title/description against
   `config.BLACKLIST_KEYWORDS` (PT-language red flags: "para peças", "avariado", "acidentado", etc.).
   `evaluate()` is the core rule: price ≤ `BUDGET`, ≥ `MIN_DISCOUNT` below the market median for that
   brand/model/2-year bucket, estimated profit (`median * RESALE_FACTOR - price`) ≥ `MIN_PROFIT`, mileage
   ≤ `MAX_MILEAGE`, not blacklisted. Market medians come from the `market_stats` SQL view (only populated
   once a bucket has ≥5 comparable ads), keyed via `stats_key()` (lowercased brand/model, year floored to
   an even 2-year bucket) — this key logic must stay identical between Python and the SQL view's `(year /
   2) * 2` bucketing or lookups silently miss.
4. **`src/notify.py`** — formats and sends the Telegram message (HTML parse mode) for each new deal.
5. **`dashboard/app.py`** — read-only Streamlit UI querying `deals_view`, `ads`, `market_stats` directly
   via `st.cache_data`. Independent of the crawler process (own Supabase client, reads whatever's currently
   in Supabase), but imports the pure modules `src.config` / `src.deal_engine` for shared constants and key
   logic (`RESALE_FACTOR`, `KM_BANDS`, `km_band()`, `fine_key()`, `ACTIVE_WINDOW_DAYS`) so they can't drift
   from the crawler's. Secrets
   resolved via `secret()`, which checks `st.secrets` first (Streamlit Cloud) then falls back to env vars
   (local `.env`).

All tunable thresholds (`BUDGET`, `MARKET_CEILING`, `MIN_DISCOUNT`, `MIN_PROFIT`, `MAX_MILEAGE`,
`CATEGORY_ID`, `DEEP_SWEEP`) are env vars loaded once in `src/config.py` — see `.env.example` for the full
list and defaults.

## Deployment

- Crawler: GitHub Actions (`.github/workflows/crawl.yml`), incremental every 30 min, deep sweep weekly
  (Sunday 03:00 UTC) via cron, or manually via `workflow_dispatch` with a `deep_sweep` checkbox. Secrets
  (`SUPABASE_URL`, `SUPABASE_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) come from repo Actions secrets.
- Dashboard: Streamlit Community Cloud, main file `dashboard/app.py`, secrets configured in the Streamlit
  app settings (same two Supabase keys).

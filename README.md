# OLX.pt Car Deal Finder 🚗

Finds flip-worthy cars on OLX.pt: buys ≤ €2.000, resells near market value, no major labor. Crawls OLX's JSON API (no browser, very cheap), stores everything in Supabase, alerts you on Telegram, and shows a live Streamlit dashboard. Runs 100% on free tiers.

## How it works

1. **Crawler** (GitHub Actions, every 30 min): pulls newest car ads ≤ €6.000 from `olx.pt/api/v1/offers/` (40 ads/request, JSON — no page rendering). A weekly deep sweep rebuilds the full market picture using price buckets to bypass OLX's pagination cap.
2. **Deal engine**: computes the market median per brand/model/2-year bucket (needs ≥5 comparable ads). An ad is a deal when: price ≤ €2.000, ≥25% below median, estimated profit (median × 0.85 − price) ≥ €300, ≤ 280.000 km, and no red-flag keywords ("para peças", "avariado", "sem documentos", "acidentado"…).
3. **Telegram** message per new deal with price, median, estimated profit and link.
4. **Dashboard** (Streamlit Cloud): deals feed, all ads, market stats.

All thresholds are env vars — see `.env.example`.

## Setup (~15 min, all free)

### 1. Supabase (database)
1. Create a project at [supabase.com](https://supabase.com) (free tier).
2. SQL Editor → paste `supabase_schema.sql` → Run.
3. Note your **Project URL** and **service_role key** (Settings → API).

### 2. Telegram bot
1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the **token**.
2. Send your new bot any message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` — your **chat id** is in `message.chat.id`.

### 3. Crawler on GitHub Actions
1. Push this folder to a GitHub repo.
2. Repo → Settings → Secrets and variables → Actions → add:
   `SUPABASE_URL`, `SUPABASE_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
3. Actions tab → "Crawl OLX.pt" → **Run workflow** with *deep sweep* checked once, to seed market stats. After that it runs itself every 30 min.

### 4. Dashboard on Streamlit Community Cloud
1. Go to [share.streamlit.io](https://share.streamlit.io) → New app → pick your repo, main file `dashboard/app.py`.
2. App settings → Secrets:
   ```toml
   SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
   SUPABASE_KEY = "your-key"
   ```

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your values
python -m src.crawler                 # one crawl (DEEP_SWEEP=1 for full sweep)
streamlit run dashboard/app.py        # dashboard at localhost:8501
```

## Notes

- The first runs won't alert much: deals only trigger once enough comparable ads exist to compute medians. Run the deep sweep first.
- OLX may rate-limit; the client backs off automatically. If the API ever changes, `src/olx_api.py` is the only file to touch.
- Estimated profit is an estimate, not a guarantee — always inspect the car and paperwork before buying.

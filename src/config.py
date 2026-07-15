import os

from dotenv import load_dotenv

load_dotenv()

# Empty is tolerated at import time so I/O-free consumers (e.g. the dashboard,
# which gets its creds from st.secrets) can import this module; db.client()
# fails fast if a DB-touching process starts without them.
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BUDGET = float(os.getenv("BUDGET", 2000))
# Crawl up to this price so market medians aren't truncated at BUDGET.
MARKET_CEILING = float(os.getenv("MARKET_CEILING", 15000))
MIN_DISCOUNT = float(os.getenv("MIN_DISCOUNT", 0.25))
MIN_PROFIT = float(os.getenv("MIN_PROFIT", 300))
MAX_MILEAGE = int(os.getenv("MAX_MILEAGE", 280000))
CATEGORY_ID = int(os.getenv("CATEGORY_ID", 378))
DEEP_SWEEP = os.getenv("DEEP_SWEEP", "0") == "1"

# How many stored ad URLs to re-check against their live OLX page per url_checker run
# (on top of the uncapped priority tier — see db.deal_ad_ids), how far back (by
# first_seen) to bother checking at all, and how fast to check them. OLX rate-limits
# individual ad-page fetches (confirmed 2026-07-14: 6 workers with no pacing got
# 403'd on ~85% of requests after the first few hundred); CONCURRENCY + DELAY_SECONDS
# together cap the aggregate request rate — keep them conservative, verify against
# real runs before pushing faster. At ~2 req/s this batch clears a multi-thousand-ad
# backlog within ~2 days at this cadence (every 4h, see verify-urls.yml).
URL_CHECK_BATCH_SIZE = int(os.getenv("URL_CHECK_BATCH_SIZE", 1500))
URL_CHECK_LOOKBACK_DAYS = int(os.getenv("URL_CHECK_LOOKBACK_DAYS", 90))
URL_CHECK_CONCURRENCY = int(os.getenv("URL_CHECK_CONCURRENCY", 2))
URL_CHECK_DELAY_SECONDS = float(os.getenv("URL_CHECK_DELAY_SECONDS", 0.5))

# Resale friction: assume you sell at ~85% of median (haggling, fees, time)
RESALE_FACTOR = 0.85

# Mileage band edges for fine market comps — must match the CASE in the
# market_stats_fine view (supabase_schema.sql).
KM_BANDS = (150_000, 250_000)

# Confidence thresholds on (sample size, IQR relative to the median):
# alta needs a big tight sample; baixa is a small or wildly spread one.
CONF_ALTA_N, CONF_ALTA_IQR = 15, 0.35
CONF_BAIXA_N, CONF_BAIXA_IQR = 8, 0.60

# An ad is "ativo" if seen within this window — must match the 8-day
# interval used by deals_view / market_liquidity (supabase_schema.sql).
ACTIVE_WINDOW_DAYS = 8

# Skip re-alerting an identical car re-listed under a new id within this window.
RELIST_DEDUPE_DAYS = 30

# Ads whose title/description mention these need labor or are unsellable.
BLACKLIST_KEYWORDS = [
    "para peças", "para pecas", "às peças", "as pecas",
    "p/ peças", "p/ pecas", "p/peças", "p/pecas",
    "para reparar", "p/ reparar", "p/reparar",
    "não funciona", "nao funciona",
    "avariado", "avariada", "avaria", "não liga", "nao liga",
    "sem documentos", "sem docs", "sem livrete", "falta legalizar", "sem matrícula",
    "motor fundido", "caixa avariada", "colaço partido",
    "para restauro", "restaurar", "projeto",
    "acidentado", "acidentada", "batido", "batida", "sinistro", "salvado",
    "sem motor", "sem caixa", "danificado", "danificada", "para abate",
]

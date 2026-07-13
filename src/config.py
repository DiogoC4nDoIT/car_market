import os

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BUDGET = float(os.getenv("BUDGET", 2000))
PRICE_CEILING = float(os.getenv("PRICE_CEILING", 6000))
# Crawl up to this price so market medians aren't truncated at PRICE_CEILING.
MARKET_CEILING = float(os.getenv("MARKET_CEILING", 15000))
MIN_DISCOUNT = float(os.getenv("MIN_DISCOUNT", 0.25))
MIN_PROFIT = float(os.getenv("MIN_PROFIT", 300))
MAX_MILEAGE = int(os.getenv("MAX_MILEAGE", 280000))
CATEGORY_ID = int(os.getenv("CATEGORY_ID", 378))
DEEP_SWEEP = os.getenv("DEEP_SWEEP", "0") == "1"

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

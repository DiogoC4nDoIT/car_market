import os

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BUDGET = float(os.getenv("BUDGET", 2000))
PRICE_CEILING = float(os.getenv("PRICE_CEILING", 6000))
MIN_DISCOUNT = float(os.getenv("MIN_DISCOUNT", 0.25))
MIN_PROFIT = float(os.getenv("MIN_PROFIT", 300))
MAX_MILEAGE = int(os.getenv("MAX_MILEAGE", 280000))
CATEGORY_ID = int(os.getenv("CATEGORY_ID", 378))
DEEP_SWEEP = os.getenv("DEEP_SWEEP", "0") == "1"

# Resale friction: assume you sell at ~85% of median (haggling, fees, time)
RESALE_FACTOR = 0.85

# Ads whose title/description mention these need labor or are unsellable.
BLACKLIST_KEYWORDS = [
    "para peças", "para pecas", "às peças", "as pecas",
    "avariado", "avariada", "avaria", "não liga", "nao liga",
    "sem documentos", "sem docs", "sem livrete", "falta legalizar", "sem matrícula",
    "motor fundido", "caixa avariada", "colaço partido",
    "para restauro", "restaurar", "projeto",
    "acidentado", "acidentada", "batido", "batida", "sinistro", "salvado",
    "sem motor", "sem caixa", "danificado", "danificada", "para abate",
]

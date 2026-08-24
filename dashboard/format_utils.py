"""Small formatting/labelling helpers shared across tabs. No Streamlit or
Supabase calls here — pure functions only, so they're easy to reason about
and reuse from the detail view, cards, and tables alike."""
import html
from datetime import datetime, timezone

import pandas as pd

CONF_META = {
    "alta": ("High", "#2f7d4f"),
    "media": ("Medium", "#c99a3f"),
    "baixa": ("Low", "#b5623a"),
}
CONF_BADGE = {"alta": "🟢 alta", "media": "🟡 média", "baixa": "🔴 baixa"}


def esc(s):
    return html.escape(str(s)) if s is not None else ""


def money(x):
    """€ formatter. Uses pd.isna() directly (not an isinstance(float) guard)
    so it also handles None, NaT, and pandas' nullable-Int64 pd.NA, not just
    plain float NaN."""
    if x is None or pd.isna(x):
        return "—"
    return f"€{x:,.0f}"


def describe_filters(filters):
    profit_lo, profit_hi = filters.get("profit", (None, None))
    km_lo, km_hi = filters.get("km", (None, None))
    year_lo, year_hi = filters.get("year", (None, None))
    clauses = [
        f"Profit {money(profit_lo)}–{money(profit_hi)}",
        f"Mileage {km_lo:,}–{km_hi:,} km",
        f"Year {year_lo}–{year_hi}",
    ]
    if filters.get("brand"):
        clauses.append(filters["brand"])
    if filters.get("model"):
        clauses.append(filters["model"])
    if filters.get("region"):
        clauses.append(filters["region"])
    if filters.get("trust"):
        clauses.append(f"Trust: {CONF_META[filters['trust']][0]}")
    if filters.get("active"):
        clauses.append("Active only")
    return " · ".join(clauses)


def verdict_for(score):
    if score >= 85:
        return "Strong", "#1c3d2e", "#e8c07a"
    if score >= 66:
        return "Fair", "#efe6d0", "#8a6a2c"
    return "Watch", "#f3e2d8", "#a4502f"


def score_color(score):
    if score >= 85:
        return "#2f6b47"
    if score >= 66:
        return "#c99a3f"
    return "#b5623a"


def minutes_since(ts: str) -> float:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).total_seconds() / 60


def comp_sold_info(last_seen, olx_created_at, url_status=None, active_window_days=None):
    """Whether a comp looks sold, and days-to-sell if computable. Prefers the
    direct url_status check (src/url_checker.py); falls back to the same
    last_seen-age inference market_liquidity uses when a comp hasn't been
    checked yet."""
    if url_status == "active":
        sold = False
    elif url_status in ("sold", "removed"):
        sold = True
    elif pd.isna(last_seen):
        return False, None
    else:
        ls = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
        sold = (datetime.now(timezone.utc) - ls).days >= active_window_days
    if not sold or pd.isna(last_seen) or pd.isna(olx_created_at):
        return sold, None
    ls = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
    created = datetime.fromisoformat(str(olx_created_at).replace("Z", "+00:00"))
    return True, ((ls - created).total_seconds() / 86400 if ls > created else None)

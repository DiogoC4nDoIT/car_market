"""Streamlit dashboard. Run locally: streamlit run dashboard/app.py
Deploy free at https://share.streamlit.io (secrets: SUPABASE_URL, SUPABASE_KEY).

This file only wires things together: load data, build the header/tab nav,
and dispatch to a tab renderer. CSS lives in styles.py, formatting helpers in
format_utils.py, all Supabase access in data.py, shared widgets in
components.py, and each tab's page logic in tabs/.
"""
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# dashboard/ isn't a package and Streamlit puts only the script's own dir on
# sys.path, so reach the repo root explicitly to share the crawler's pure
# modules (thresholds + market-key logic) instead of hand-mirroring them.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard import styles  # noqa: E402
from dashboard.context import Context  # noqa: E402
from dashboard.data import load  # noqa: E402
from dashboard.format_utils import minutes_since  # noqa: E402
from dashboard.tabs import (  # noqa: E402
    render_ads_tab,
    render_deals_tab,
    render_detail,
    render_favourites_tab,
    render_market_tab,
)

load_dotenv()

st.set_page_config(page_title="Stand · OLX Flip Radar", page_icon="🚗", layout="wide")
styles.inject()

st.session_state.setdefault("active_tab", "deals")
st.session_state.setdefault("open_id", None)

if st.session_state.open_id is None and "ad" in st.query_params:
    try:
        st.session_state.open_id = int(st.query_params["ad"])
    except (TypeError, ValueError):
        pass

deals = load("deals_view", order="created_at")
ads = load("ads", order="first_seen", limit=5000)
runs = load("crawl_runs", order="started_at", limit=1)
stats = load("market_stats")
fine_stats = load("market_stats_fine")
fuel_stats = load("market_stats_fuel")
liq = load("market_liquidity")
flags = load("ad_flags")
searches = load("saved_searches")

if not flags.empty:
    skipped_ids = set(flags.loc[flags["flag"] == "skipped", "ad_id"].astype(int))
    fav_rows = flags.loc[flags["flag"] == "favourite"]
    fav_ids = set(fav_rows["ad_id"].astype(int))
    # Ads the crawler auto-favourited because they matched a saved search
    # (source='saved_search', src.db.set_favourite_from_search_match) are
    # tracked the same as manual ones for price-drop alerts, but the Fav
    # button on the dashboard should only ever *remove* an ad the user
    # actually starred themselves — see manual_fav_ids usage in components.py.
    manual_fav_ids = set(fav_rows.loc[fav_rows["source"] == "manual", "ad_id"].astype(int))
else:
    skipped_ids = set()
    fav_ids = set()
    manual_fav_ids = set()

if not ads.empty:
    ads = ads.copy()
    ads["year_bucket"] = (ads["year"] // 2 * 2).astype("Int64")

if not deals.empty:
    deals = deals.copy()
    deals["year_bucket"] = (deals["year"] // 2 * 2).astype("Int64")
    if not liq.empty:
        deals = deals.merge(liq, on=["brand", "model", "year_bucket"], how="left")
    if not stats.empty:
        deals = deals.merge(
            stats[["brand", "model", "year_bucket", "p25", "p75"]],
            on=["brand", "model", "year_bucket"], how="left",
        )
    # deal_engine's `score` is an unbounded profit-weighted figure (est_profit * discount *
    # confidence factor), not the 0-100 scale the design's verdict tiers/score dial assume —
    # rescale it across the current deal set for display and verdict thresholds only; sorting
    # still uses the raw `score`.
    score_min, score_max = deals["score"].min(), deals["score"].max()
    score_span = score_max - score_min
    deals["display_score"] = (
        (deals["score"] - score_min) / score_span * 100 if score_span else 50.0
    )

ctx = Context(
    deals=deals, ads=ads, stats=stats, fine_stats=fine_stats, fuel_stats=fuel_stats,
    liq=liq, flags=flags, searches=searches, skipped_ids=skipped_ids, fav_ids=fav_ids,
    manual_fav_ids=manual_fav_ids,
)

if runs.empty:
    status_text = "no crawl runs yet"
else:
    mins = minutes_since(runs.iloc[0]["started_at"])
    status_text = f"● updated {mins:.0f} min ago" if mins <= 120 else f"⚠️ stale — updated {mins:.0f} min ago"

st.markdown(f"""
<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;padding:14px 20px;
     background:var(--app-tab-bar);color:var(--app-tab-bar-contrast);border-radius:var(--radius);
     flex-wrap:wrap;margin-bottom:14px">
  <div style="display:flex;align-items:center;gap:10px">
    <span style="font-size:20px">🚗</span>
    <span style="font:500 20px var(--font-family)">Stand</span>
    <span style="width:5px;height:5px;border-radius:50%;background:var(--primary-main);display:inline-block"></span>
    <span style="font:400 11px var(--font-family-monospace);color:#ffffffb3;letter-spacing:.5px">OLX.PT FLIP RADAR</span>
  </div>
  <span style="font:400 11px var(--font-family-monospace);color:#ffffffb3">{status_text}</span>
</div>
""", unsafe_allow_html=True)

TABS = [
    ("deals", "Deals", "sell"),
    ("favourites", "Favourites", "star"),
    ("market", "Market", "insights"),
    ("ads", "Ads", "table_rows"),
]
with st.sidebar:
    for key, label, icon in TABS:
        active = st.session_state.active_tab == key and st.session_state.open_id is None
        # A disabled button (rather than a raw HTML pill) so the "active" nav item
        # renders through Streamlit's own self-hosted Material Symbols icon font —
        # the externally-loaded "Material Icons" webfont this design's raw <span>
        # icons depend on doesn't reliably load in every environment (verified: it
        # silently falls back to literal icon-name text, e.g. "directions_car").
        # Collapsing to icon-only is left entirely to Streamlit's own native sidebar
        # toggle rather than a second custom control — two different "collapse"
        # buttons with different scopes (whole sidebar vs. just labels) was
        # confusing, not useful.
        clicked = st.button(label, icon=f":material/{icon}:", key=f"tab_{key}",
                             use_container_width=True, disabled=active)
        if clicked:
            st.session_state.active_tab = key
            st.session_state.open_id = None
            st.query_params.pop("ad", None)
            st.rerun()

if st.session_state.open_id is not None:
    render_detail(ctx, st.session_state.open_id)
elif st.session_state.active_tab == "deals":
    render_deals_tab(ctx)
elif st.session_state.active_tab == "favourites":
    render_favourites_tab(ctx)
elif st.session_state.active_tab == "market":
    render_market_tab(ctx)
else:
    render_ads_tab()

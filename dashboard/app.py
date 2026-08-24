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
    fav_ids = set(flags.loc[flags["flag"] == "favourite", "ad_id"].astype(int))
else:
    skipped_ids = set()
    fav_ids = set()

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
)

if runs.empty:
    status_text = "no crawl runs yet"
else:
    mins = minutes_since(runs.iloc[0]["started_at"])
    status_text = f"● updated {mins:.0f} min ago" if mins <= 120 else f"⚠️ stale — updated {mins:.0f} min ago"

st.markdown(f"""
<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;padding:14px 20px;
     background:#1c3d2e;color:#f3eeddf2;border-radius:12px;flex-wrap:wrap;margin-bottom:14px">
  <div style="display:flex;align-items:baseline;gap:10px">
    <span style="font:600 20px 'Newsreader',serif">Stand</span>
    <span style="width:5px;height:5px;border-radius:50%;background:#e8c07a;display:inline-block"></span>
    <span style="font:400 11px 'JetBrains Mono',monospace;color:#9db6a7;letter-spacing:.5px">OLX.PT FLIP RADAR</span>
  </div>
  <span style="font:400 11px 'JetBrains Mono',monospace;color:#9db6a7">{status_text}</span>
</div>
""", unsafe_allow_html=True)

TABS = [("deals", "Deals"), ("favourites", "Favourites"), ("market", "Market"), ("ads", "Ads")]
tab_cols = st.columns(len(TABS))
for col, (key, label) in zip(tab_cols, TABS):
    with col:
        if st.session_state.active_tab == key and st.session_state.open_id is None:
            st.markdown(
                f'<div style="text-align:center;padding:10px 18px;border-radius:9px;background:#e8c07a;'
                f'color:#3a2f16;font:600 13.5px \'Instrument Sans\'">{label}</div>',
                unsafe_allow_html=True,
            )
        else:
            if st.button(label, key=f"tab_{key}", use_container_width=True):
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

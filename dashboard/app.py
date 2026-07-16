"""Streamlit dashboard. Run locally: streamlit run dashboard/app.py
Deploy free at https://share.streamlit.io (secrets: SUPABASE_URL, SUPABASE_KEY).
"""
import html
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from st_aggrid import AgGrid, GridOptionsBuilder
from st_aggrid.shared import JsCode
from supabase import create_client

# dashboard/ isn't a package and Streamlit puts only the script's own dir on
# sys.path, so reach the repo root explicitly to share the crawler's pure
# modules (thresholds + market-key logic) instead of hand-mirroring them.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, deal_engine  # noqa: E402

load_dotenv()

st.set_page_config(page_title="Stand · OLX Flip Radar", page_icon="🚗", layout="wide")

DEALS_PAGE_SIZE = 20

CONF_META = {
    "alta": ("High", "#2f7d4f"),
    "media": ("Medium", "#c99a3f"),
    "baixa": ("Low", "#b5623a"),
}
CONF_BADGE = {"alta": "🟢 alta", "media": "🟡 média", "baixa": "🔴 baixa"}


def esc(s):
    return html.escape(str(s)) if s is not None else ""


def money(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"€{x:,.0f}"


def render_bar_list(rows, label_fn, value_fn, fmt_fn, color="linear-gradient(90deg,#1c3d2e,#3f8659)", count_fn=None):
    max_val = max((value_fn(r) for r in rows), default=0)
    for r in rows:
        v = value_fn(r)
        pct = v / max_val * 100 if max_val else 0
        count_html = (
            f'<span style="width:56px;flex:none;text-align:right;font-size:11px;color:#9a9482">'
            f'{esc(count_fn(r))}</span>'
            if count_fn else ""
        )
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">'
            f'<span style="width:220px;flex:none;font-size:12px;color:#5b5647;overflow:hidden;'
            f'text-overflow:ellipsis;white-space:nowrap">{esc(label_fn(r))}</span>'
            f'<div style="flex:1;height:16px;background:#e8dfca;border-radius:4px;overflow:hidden">'
            f'<div style="height:100%;background:{color};width:{pct:.0f}%"></div></div>'
            f'<span style="width:70px;flex:none;text-align:right;font:500 12px \'JetBrains Mono\',monospace">'
            f'{fmt_fn(v)}</span>{count_html}</div>',
            unsafe_allow_html=True,
        )


def render_filterable_table(df, column_config, key, height=700, paginate=False, page_size=200):
    """st.dataframe replacement with per-column header filters (ag-Grid)."""
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(filter=True, sortable=True,
                                 resizable=True, editable=False)
    for field, cfg in column_config.items():
        gb.configure_column(field, **cfg)
    if paginate:
        gb.configure_pagination(enabled=True, paginationAutoPageSize=False, paginationPageSize=page_size)
    AgGrid(df, gridOptions=gb.build(), height=height, theme="streamlit",
           fit_columns_on_grid_load=True, key=key, allow_unsafe_jscode=True)


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


def pagination_controls(key, total_pages, widget_key=None):
    widget_key = widget_key or key
    st.session_state.setdefault(key, 1)
    page = min(max(st.session_state[key], 1), total_pages)
    st.session_state[key] = page
    c1, c2, c3 = st.columns([1, 3, 1])
    with c1:
        if st.button("← Prev", key=f"{widget_key}_prev", disabled=page <= 1, use_container_width=True):
            st.session_state[key] = page - 1
            st.rerun()
    with c2:
        st.markdown(
            f'<div style="text-align:center;padding-top:8px;font-size:12px;color:#8c856f">'
            f'Page {page} of {total_pages}</div>',
            unsafe_allow_html=True,
        )
    with c3:
        if st.button("Next →", key=f"{widget_key}_next", disabled=page >= total_pages, use_container_width=True):
            st.session_state[key] = page + 1
            st.rerun()
    return page


def secret(name):
    try:
        value = st.secrets.get(name)
    except st.errors.StreamlitSecretNotFoundError:
        value = None
    return value or os.getenv(name)


@st.cache_resource
def sb():
    return create_client(secret("SUPABASE_URL"), secret("SUPABASE_KEY"))


def _fetch_paged(q, limit=None):
    """PostgREST caps a single request at its configured max-rows (commonly 1000)
    regardless of the .limit() we pass, so page via .range() until `limit` is hit
    or the result set is exhausted — otherwise `limit=5000` silently truncates
    to ~1000. `limit=None` pages until the result set is exhausted (fetch everything)."""
    rows, offset = [], 0
    while limit is None or offset < limit:
        chunk = 1000 if limit is None else min(1000, limit - offset)
        page = q.range(offset, offset + chunk - 1).execute().data
        rows.extend(page)
        if len(page) < chunk:
            break
        offset += chunk
    return pd.DataFrame(rows)


@st.cache_data(ttl=120)
def load(table, order=None, limit=2000):
    q = sb().table(table).select("*")
    if order:
        q = q.order(order, desc=True)
    return _fetch_paged(q, limit)


@st.cache_data(ttl=120)
def count_rows(table):
    return sb().table(table).select("id", count="exact").limit(1).execute().count


@st.cache_data(ttl=120)
def count_ads(brand=None, region=None, fuel=None, yr_lo=None, yr_hi=None,
               p_lo=None, p_hi=None, min_last_seen=None, min_first_seen=None):
    """Exact server-side count matching the Market tab filters — the `ads` df loaded via
    `load()` is capped (currently 5000 of 13k+ rows) for the charts/deep-dive below, so KPI
    cards must count against the real table instead or they'd plateau at the cap."""
    q = sb().table("ads").select("id", count="exact")
    if brand and brand != "All brands":
        q = q.eq("brand", brand)
    if region and region != "All regions":
        q = q.eq("region", region)
    if fuel and fuel != "All fuels":
        q = q.eq("fuel", fuel)
    if yr_lo is not None:
        q = q.gte("year", yr_lo).lte("year", yr_hi)
    if p_lo is not None:
        q = q.gte("price", p_lo).lte("price", p_hi)
    if min_last_seen is not None:
        q = q.gte("last_seen", min_last_seen)
    if min_first_seen is not None:
        q = q.gte("first_seen", min_first_seen)
    return q.limit(1).execute().count


def set_flag(ad_id: int, flag: str):
    sb().table("ad_flags").upsert({"ad_id": int(ad_id), "flag": flag}).execute()
    st.cache_data.clear()


def clear_flag(ad_id: int, flag: str):
    sb().table("ad_flags").delete().eq("ad_id", int(ad_id)).eq("flag", flag).execute()
    st.cache_data.clear()


def toggle_flag(ad_id: int, flag: str, currently_set: bool):
    (clear_flag if currently_set else set_flag)(ad_id, flag)


def create_saved_search(name: str, filters: dict):
    sb().table("saved_searches").insert({"name": name, "filters": filters}).execute()
    st.cache_data.clear()


def delete_saved_search(search_id: int):
    sb().table("saved_searches").delete().eq("id", int(search_id)).execute()
    st.cache_data.clear()


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """Applies a saved-search filter dict to a deals-shaped dataframe using the same
    predicate the crawler uses (deal_engine.matches_filters) before sending a "new
    favourite deal" Telegram alert, so the two can never disagree on what matches."""
    if df.empty:
        return df
    mask = df.apply(lambda r: deal_engine.matches_filters(r.to_dict(), filters), axis=1)
    return df[mask]


@st.cache_data(ttl=120)
def load_all_ads():
    return _fetch_paged(sb().table("ads").select("*").order("first_seen", desc=True))


@st.cache_data(ttl=120)
def load_comps(brand, model, year_lo, year_hi, fuel=None, mileage_lo=None, mileage_hi=None):
    """Fetch comps directly from Supabase (uncapped), unlike the 5000-row `ads` df. `fuel`
    is always enforced when known (different fuel types price differently); mileage band is
    only passed when it matches the fine basis deal_engine.evaluate() used for this deal's
    stored median (see deal_engine.fine_key())."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    q = (sb().table("ads").select("*")
         .eq("brand", brand).eq("model", model)
         .gte("year", year_lo).lte("year", year_hi)
         .eq("is_blacklisted", False).gt("price", 100).gte("last_seen", cutoff))
    if fuel is not None:
        q = q.eq("fuel", fuel)
    if mileage_lo is not None:
        q = q.gte("mileage", mileage_lo)
    if mileage_hi is not None:
        q = q.lt("mileage", mileage_hi)
    return _fetch_paged(q, 2000)


@st.cache_data(ttl=120)
def load_price_history(ad_ids: tuple):
    """price_history has no brand/model of its own, so trend lookups are keyed off
    a caller-supplied set of ad ids (usually from an already brand/model-filtered
    ads slice) and batched at 500 ids/request like db.py's known_prices()."""
    if not ad_ids:
        return pd.DataFrame()
    frames = []
    for i in range(0, len(ad_ids), 500):
        chunk = list(ad_ids[i:i + 500])
        res = sb().table("price_history").select("*").in_("ad_id", chunk).execute()
        frames.append(pd.DataFrame(res.data))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def minutes_since(ts: str) -> float:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).total_seconds() / 60


def comp_sold_info(last_seen, olx_created_at, url_status=None):
    """Whether a comp looks sold, and days-to-sell if computable. Prefers the
    direct url_status check (src/url_checker.py); falls back to the same 8-day
    last_seen inference market_liquidity uses when a comp hasn't been checked yet."""
    if url_status == "active":
        sold = False
    elif url_status in ("sold", "removed"):
        sold = True
    elif pd.isna(last_seen):
        return False, None
    else:
        ls = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
        sold = (datetime.now(timezone.utc) - ls).days >= config.ACTIVE_WINDOW_DAYS
    if not sold or pd.isna(last_seen) or pd.isna(olx_created_at):
        return sold, None
    ls = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
    created = datetime.fromisoformat(str(olx_created_at).replace("Z", "+00:00"))
    return True, ((ls - created).total_seconds() / 86400 if ls > created else None)


st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=Instrument+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

.stApp { background:#efeadd; }
.stApp, .stApp p, .stApp span, .stApp div, .stApp label { font-family:'Instrument Sans',system-ui,sans-serif; }
h1, h2, h3 { font-family:'Newsreader',serif !important; color:#22201a; }
div[data-testid="stMetricValue"] { font-family:'Newsreader',serif; color:#22201a; }
div[data-testid="stMetricLabel"] { font-family:'JetBrains Mono',monospace; font-size:10px !important;
  letter-spacing:.5px; color:#8c856f !important; text-transform:uppercase; }
div[data-testid="stButton"] button {
  border-radius:9px; border:1px solid #ddd4bd; background:#faf7ef; color:#5b5647;
  font-family:'Instrument Sans',sans-serif; font-weight:500;
}
div[data-testid="stButton"] button:hover { background:#f1e9d8; border-color:#c9bf9f; color:#3a3626; }
div[data-testid="stLinkButton"] a {
  background:#e8c07a !important; color:#3a2f16 !important; border:none !important; font-weight:600 !important;
}
div[data-testid="stSlider"] div[role="slider"] { background-color:#1c3d2e !important; border-color:#1c3d2e !important; }
div[data-testid="stSlider"] div[data-baseweb="slider"] > div > div { background:#1c3d2e !important; }
div[data-testid="stSlider"] span { color:#c99a3f !important; }
div[data-baseweb="select"] > div, div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
  background:#fff !important; border-color:#d8cfb8 !important;
}
div[data-testid="stNumberInput"] input, div[data-testid="stTextInput"] input { background:#fff !important; border-color:#d8cfb8 !important; }
div[data-testid="stCheckbox"] input[type="checkbox"] { accent-color:#1c3d2e; }
.stand-mono { font-family:'JetBrains Mono',monospace; }
.stand-row-title { font-family:'Newsreader',serif; font-weight:500; font-size:15px; color:#22201a; }
.stand-meta { font-size:12px; color:#8c856f; margin-top:2px; }
.stand-label { font-family:'JetBrains Mono',monospace; font-size:10px; color:#a09a84; letter-spacing:.5px; }
.stand-badge { font:600 10px 'JetBrains Mono',monospace; padding:4px 8px; border-radius:6px; letter-spacing:.4px; }
.stand-bar-bg { height:6px; border-radius:3px; background:#e8dfca; overflow:hidden; margin-top:6px; }
.stand-bar-fill { height:100%; border-radius:3px; background:linear-gradient(90deg,#2f6b47,#3f8659); }
.stand-photo { width:100%; height:64px; border-radius:7px;
  background:repeating-linear-gradient(135deg,#eae2d0 0 7px,#e2d9c4 7px 14px);
  display:flex; align-items:center; justify-content:center;
  font:400 9px 'JetBrains Mono',monospace; color:#a89e83; }
.stand-card { background:#f2ecdc; border:1px solid #e7dfca; border-radius:11px; padding:16px 18px; }
.st-key-save_search_card > div { background:#f2ecdc; border-color:#e7dfca; }
</style>
""", unsafe_allow_html=True)

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
  <span style="font:400 11px 'JetBrains Mono',monospace;color:#9db6a7">{esc(status_text)}</span>
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
                st.rerun()


def render_deal_card(d, key_prefix=""):
    verdict, vbg, vcolor = verdict_for(d["display_score"])
    conf_label, conf_color = CONF_META.get(d["confidence"], ("—", "#a09a84"))
    with st.container(border=True):
        c0, c1, c2, c3, c4, c5 = st.columns([0.7, 3, 2.2, 1.8, 1.1, 1.4])
        with c0:
            if pd.notna(d.get("photo_url")):
                st.image(d["photo_url"], use_container_width=True)
            else:
                st.markdown('<div class="stand-photo">PHOTO</div>', unsafe_allow_html=True)
            if d.get("status") == "desaparecido":
                st.caption("👻 gone")
        with c1:
            year = int(d["year"]) if pd.notna(d.get("year")) else "?"
            km = f"{int(d['mileage']):,}" if pd.notna(d.get("mileage")) else "?"
            fuel = d["fuel"] if pd.notna(d.get("fuel")) else "?"
            region = d["region"] if pd.notna(d.get("region")) else "?"
            st.markdown(
                f'<div class="stand-row-title">{esc(d["title"])}</div>'
                f'<div class="stand-meta">{year} · {km} km · {esc(fuel)} · {esc(region)}</div>',
                unsafe_allow_html=True,
            )
        with c2:
            bar_pct = min(100, d["price"] / d["median_price"] * 100) if d["median_price"] else 0
            st.markdown(
                f'<div style="display:flex;align-items:baseline;gap:6px">'
                f'<span class="stand-mono" style="font-weight:600">{money(d["price"])}</span>'
                f'<span style="font-size:10.5px;color:#9a927b">/{money(d["median_price"])} mkt</span></div>'
                f'<div class="stand-bar-bg"><div class="stand-bar-fill" style="width:{bar_pct:.0f}%"></div></div>'
                f'<div class="stand-mono" style="font-size:11px;color:#c99a3f;margin-top:5px">'
                f'{d["discount"] * 100:.0f}% below median</div>',
                unsafe_allow_html=True,
            )
        with c3:
            sell = d.get("median_days_to_sell")
            sell_text = f"~{int(sell)}d to sell" if pd.notna(sell) else "—"
            drop = d.get("price_drop")
            drop_html = (f'<span style="color:#a4502f;font-weight:500"> · ↓{money(drop)}</span>'
                         if pd.notna(drop) else "")
            days = int(d["days_listed"]) if pd.notna(d.get("days_listed")) else 0
            n = int(d["n"]) if pd.notna(d.get("n")) else 0
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:6px">'
                f'<span style="width:8px;height:8px;border-radius:50%;background:{conf_color};'
                f'display:inline-block"></span><span style="font-size:12px">{conf_label} trust · {n} comps</span></div>'
                f'<div style="font-size:12px;color:#6a6454;margin-top:6px">{sell_text} · {days}d listed{drop_html}</div>',
                unsafe_allow_html=True,
            )
        with c4:
            st.markdown(
                f'<span class="stand-badge" style="background:{vbg};color:{vcolor}">{verdict.upper()}</span>'
                f'<div style="font:600 17px \'Newsreader\',serif;color:#2f6b47;margin-top:6px">'
                f'+{money(d["est_profit"])}</div>'
                f'<div class="stand-label">est. margin</div>',
                unsafe_allow_html=True,
            )
        with c5:
            ad_id = int(d["ad_id"])
            is_fav = ad_id in fav_ids
            if st.button("Open", key=f"{key_prefix}open_{ad_id}", use_container_width=True):
                st.session_state.open_id = ad_id
                st.rerun()
            if st.button("★ Fav" if is_fav else "☆ Fav", key=f"{key_prefix}fav_{ad_id}", use_container_width=True):
                toggle_flag(ad_id, "favourite", is_fav)
                st.rerun()
            if st.button("Skip", key=f"{key_prefix}skip_{ad_id}", use_container_width=True):
                set_flag(ad_id, "skipped")
                st.rerun()


def render_deals_tab():
    if deals.empty:
        st.info("No deals yet — the crawler needs a few runs to build market stats.")
        return

    profit_lo, profit_hi = min(0, int(deals["est_profit"].min())), int(deals["est_profit"].max())
    if profit_lo == profit_hi:
        profit_hi += 1
    profit_default_lo = max(profit_lo, min(0, profit_hi))
    km_series = deals["mileage"].dropna()
    km_lo, km_hi = (int(km_series.min()), int(km_series.max())) if not km_series.empty else (0, 300_000)
    if km_lo == km_hi:
        km_hi += 1
    year_series = deals["year"].dropna()
    year_lo, year_hi = (int(year_series.min()), int(year_series.max())) if not year_series.empty else (1980, 2030)
    if year_lo == year_hi:
        year_hi += 1

    # Streamlit clears a widget's session_state entry on any run where the widget isn't
    # instantiated (e.g. while a deal's detail view is showing instead of this tab), so
    # keying the widgets alone doesn't survive an Open -> Back round trip. Keep the real
    # values in this plain dict instead, which is never subject to that auto-clear.
    st.session_state.setdefault("deals_filters", {})
    saved = st.session_state.deals_filters

    def clamp(pair, lo, hi):
        a, b = pair
        return max(lo, min(a, hi)), max(lo, min(b, hi))

    def restore_index(options, saved_value):
        return options.index(saved_value) if saved_value in options else 0

    with st.container(border=True):
        f1, f2, f3 = st.columns(3)
        min_profit, max_profit = f1.slider(
            "PROFIT (€)", profit_lo, profit_hi,
            clamp(saved.get("profit", (profit_default_lo, profit_hi)), profit_lo, profit_hi),
            step=10, key="deals_filter_profit",
        )
        min_km, max_km = f2.slider(
            "MILEAGE (KM)", km_lo, km_hi,
            clamp(saved.get("km", (km_lo, km_hi)), km_lo, km_hi),
            step=1000, key="deals_filter_km",
        )
        min_year, max_year = f3.slider(
            "YEAR", year_lo, year_hi,
            clamp(saved.get("year", (year_lo, year_hi)), year_lo, year_hi),
            key="deals_filter_year",
        )
        f4, f5, f6, f7, f8 = st.columns([1.3, 1.3, 1.1, 1, 1.1])
        brand_opts = ["All brands"] + sorted(deals["brand"].dropna().unique())
        brand = f4.selectbox("BRAND", brand_opts, index=restore_index(brand_opts, saved.get("brand")),
                              key="deals_filter_brand")
        model_opts = ["All models"] + sorted(deals["model"].dropna().unique())
        model = f5.selectbox("MODEL", model_opts, index=restore_index(model_opts, saved.get("model")),
                              key="deals_filter_model")
        region_opts = ["All regions"] + sorted(deals["region"].dropna().unique())
        region = f6.selectbox("REGION", region_opts, index=restore_index(region_opts, saved.get("region")),
                               key="deals_filter_region")
        trust_opts = ["All levels", "alta", "media", "baixa"]
        conf = f7.selectbox("TRUST", trust_opts, index=restore_index(trust_opts, saved.get("trust")),
                             format_func=lambda c: c if c == "All levels" else CONF_META[c][0],
                             key="deals_filter_trust")
        only_active = f8.checkbox("Active only", value=saved.get("active", True),
                                   key="deals_filter_active")

    saved.update(profit=(min_profit, max_profit), km=(min_km, max_km), year=(min_year, max_year),
                 brand=brand, model=model, region=region, trust=conf, active=only_active)

    filters = {
        "profit": (min_profit, max_profit), "km": (min_km, max_km), "year": (min_year, max_year),
        "brand": None if brand == "All brands" else brand,
        "model": None if model == "All models" else model,
        "region": None if region == "All regions" else region,
        "trust": None if conf == "All levels" else conf,
        "active": only_active,
    }
    view = apply_filters(deals[~deals["ad_id"].isin(skipped_ids)], filters)

    with st.container(border=True, key="save_search_card"):
        st.markdown('<div class="stand-label" style="margin-bottom:10px">SAVE AS FAVOURITE DEAL</div>',
                    unsafe_allow_html=True)
        sn1, sn2 = st.columns([4, 1])
        search_name = sn1.text_input(
            "Search name", key="new_search_name", label_visibility="collapsed",
            placeholder="Name this filter combo, e.g. \"Cheap diesel wagons\"",
        )
        if sn2.button("💾 Save search", use_container_width=True):
            if search_name.strip():
                create_saved_search(search_name.strip(), filters)
                st.success(f"Saved “{search_name.strip()}” to Favourites → Favourite deals.")
                st.rerun()
            else:
                st.warning("Give the search a name first.")

    with st.container(border=True):
        s1, s2, s3, s4 = st.columns([1, 1, 1, 1])
        s1.metric("LIVE DEALS", len(view))
        s2.metric("TOTAL EST. PROFIT", money(view["est_profit"].sum()) if len(view) else "—")
        s3.metric("AVG DISCOUNT", f"{view['discount'].mean() * 100:.0f}%" if len(view) else "—")
        with s4:
            if skipped_ids:
                st.caption(f"{len(skipped_ids)} skipped")
                if st.button("Undo all", key="undo_all"):
                    for ad_id in skipped_ids:
                        clear_flag(ad_id, "skipped")
                    st.rerun()

    view = view.sort_values("score", ascending=False)
    total_pages = max(1, -(-len(view) // DEALS_PAGE_SIZE))

    st.write("")
    page = pagination_controls("deals_page", total_pages)
    start = (page - 1) * DEALS_PAGE_SIZE
    st.write("")
    for _, d in view.iloc[start:start + DEALS_PAGE_SIZE].iterrows():
        render_deal_card(d)

    st.write("")
    pagination_controls("deals_page", total_pages, widget_key="deals_page_bottom")


def render_favourites_tab():
    if not fav_ids and searches.empty:
        st.info("No favourites yet — tap ☆ Fav on a deal to save it, or save a filter combo "
                 "from the Deals tab as a favourite deal.")
        return

    st.markdown("**★ Favourite ads**")
    if not fav_ids:
        st.caption("No starred ads yet — tap ☆ Fav on a deal card to pin it here.")
    else:
        view = deals[deals["ad_id"].isin(fav_ids)].sort_values("score", ascending=False)
        st.caption(f"{len(view)} favourited")
        for _, d in view.iterrows():
            render_deal_card(d, key_prefix="favad_")

    st.write("")
    st.markdown("**⭐ Favourite deals**")
    st.caption("Saved filter combos from the Deals tab. New matches and price changes on "
               "favourite ads are also sent to Telegram.")
    if searches.empty:
        st.caption("No favourite deals saved yet — set filters on the Deals tab and use "
                   "\"Save as favourite deal\".")
        return

    for _, search in searches.sort_values("created_at").iterrows():
        search_id, name, filters = int(search["id"]), search["name"], search["filters"]
        with st.container(border=True):
            h1, h2 = st.columns([5, 1])
            h1.markdown(f'<div class="stand-row-title">{esc(name)}</div>', unsafe_allow_html=True)
            if h2.button("🗑 Delete", key=f"del_search_{search_id}", use_container_width=True):
                delete_saved_search(search_id)
                st.rerun()

            view = apply_filters(deals[~deals["ad_id"].isin(skipped_ids)], filters)
            view = view.sort_values("score", ascending=False)
            if view.empty:
                st.caption("No live deals match this search right now.")
            else:
                st.caption(f"{len(view)} matching deal{'s' if len(view) != 1 else ''}")
                st.write("")
                for _, d in view.iterrows():
                    render_deal_card(d, key_prefix=f"search{search_id}_")


def render_market_tab():
    if stats.empty:
        st.info("Market stats appear once ≥5 comparable ads exist per model.")
        return

    brand_opts = sorted(set(stats["brand"].dropna()) | set(ads["brand"].dropna()))
    region_opts = sorted(ads["region"].dropna().unique())
    fuel_opts = sorted(ads["fuel"].dropna().unique())
    year_series = ads["year"].dropna()
    yr_lo_b, yr_hi_b = (int(year_series.min()), int(year_series.max())) if not year_series.empty else (1980, 2030)
    if yr_lo_b == yr_hi_b:
        yr_hi_b += 1
    price_series = ads["price"].dropna()
    p_lo_b, p_hi_b = (int(price_series.min()), int(price_series.max())) if not price_series.empty else (0, 100_000)
    if p_lo_b == p_hi_b:
        p_hi_b += 1

    with st.container(border=True):
        f1, f2, f3 = st.columns(3)
        brand = f1.selectbox("BRAND", ["All brands"] + brand_opts, key="market_filter_brand")
        region = f2.selectbox("REGION", ["All regions"] + region_opts, key="market_filter_region")
        fuel = f3.selectbox("FUEL", ["All fuels"] + fuel_opts, key="market_filter_fuel")
        f4, f5 = st.columns(2)
        yr_lo, yr_hi = f4.slider("YEAR", yr_lo_b, yr_hi_b, (yr_lo_b, yr_hi_b), key="market_filter_year")
        p_lo, p_hi = f5.slider("PRICE (€)", p_lo_b, p_hi_b, (p_lo_b, p_hi_b), step=100, key="market_filter_price")

    # A fuel filter switches the model table/charts to the fuel-specific view too —
    # otherwise picking "Diesel" only affects the breakdown charts below while the
    # main model list/medians stay a fuel-blind blend (the exact bug this whole
    # fuel-matching pass exists to fix, just at the aggregate level instead of a
    # single deal's comps).
    stats_f = (fuel_stats[fuel_stats["fuel"] == fuel].drop(columns="fuel").copy()
               if fuel != "All fuels" and not fuel_stats.empty else stats.copy())
    ads_f = ads.copy()
    if brand != "All brands":
        stats_f = stats_f[stats_f["brand"] == brand]
        ads_f = ads_f[ads_f["brand"] == brand]
    if region != "All regions":
        ads_f = ads_f[ads_f["region"] == region]
    if fuel != "All fuels":
        ads_f = ads_f[ads_f["fuel"] == fuel]
    stats_f = stats_f[(stats_f["year_bucket"] + 1 >= yr_lo) & (stats_f["year_bucket"] <= yr_hi)]
    ads_f = ads_f[ads_f["year"].isna() | ads_f["year"].between(yr_lo, yr_hi)]
    stats_f = stats_f[stats_f["median_price"].between(p_lo, p_hi)]
    ads_f = ads_f[ads_f["price"].isna() | ads_f["price"].between(p_lo, p_hi)]

    display = stats_f.merge(liq, on=["brand", "model", "year_bucket"], how="left") if not liq.empty else stats_f.copy()
    display = display.sort_values("n", ascending=False, na_position="last")

    now_ts = datetime.now(timezone.utc)
    active_cutoff = (now_ts - timedelta(days=config.ACTIVE_WINDOW_DAYS)).isoformat()
    week_cutoff = (now_ts - timedelta(days=7)).isoformat()
    count_kwargs = dict(brand=brand, region=region, fuel=fuel, yr_lo=yr_lo, yr_hi=yr_hi, p_lo=p_lo, p_hi=p_hi)
    tracked_ads = count_ads(**count_kwargs)
    active_now = count_ads(**count_kwargs, min_last_seen=active_cutoff)
    new_week = count_ads(**count_kwargs, min_first_seen=week_cutoff)
    days_to_sell = display["median_days_to_sell"].dropna() if "median_days_to_sell" in display else pd.Series(dtype=float)

    with st.container(border=True):
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("TRACKED ADS", tracked_ads)
        k2.metric("ACTIVE NOW", active_now)
        k3.metric("NEW THIS WEEK", new_week)
        k4.metric("TRACKED MODELS", len(display))
        k5.metric("AVG DAYS TO SELL", f"~{days_to_sell.mean():.0f}d" if not days_to_sell.empty else "—")

    st.caption(f"Market snapshot across {len(display)} tracked models · "
               f"medians need ≥5 comparable ads in the last 90 days")
    if tracked_ads > len(ads):
        st.caption(f"Regional/fuel breakdown and deep-dive below are based on a sample "
                   f"of the {len(ads):,} most recently added ads, not all {tracked_ads:,}.")

    if display.empty:
        st.info("No models match these filters.")
    else:
        table = display.assign(
            model_label=display["brand"] + " " + display["model"],
            year_label=display["year_bucket"].astype(int).astype(str) + "–"
                       + (display["year_bucket"].astype(int) + 1).astype(str),
        )
        euro_fmt = JsCode("function(p){return p.value==null?'':'€'+Math.round(p.value).toLocaleString();}")
        days_fmt = JsCode("function(p){return p.value==null?'':Math.round(p.value)+' d';}")
        render_filterable_table(
            table[["model_label", "year_label", "n", "median_price", "p25", "p75",
                   "active_ads", "median_days_to_sell"]],
            column_config={
                "model_label": dict(header_name="Model"),
                "year_label": dict(header_name="Year"),
                "n": dict(header_name="N", type=["numericColumn"], filter="agNumberColumnFilter"),
                "median_price": dict(header_name="Median", type=["numericColumn"],
                                      filter="agNumberColumnFilter", valueFormatter=euro_fmt),
                "p25": dict(header_name="P25", type=["numericColumn"],
                            filter="agNumberColumnFilter", valueFormatter=euro_fmt),
                "p75": dict(header_name="P75", type=["numericColumn"],
                            filter="agNumberColumnFilter", valueFormatter=euro_fmt),
                "active_ads": dict(header_name="Active", type=["numericColumn"], filter="agNumberColumnFilter"),
                "median_days_to_sell": dict(header_name="Days to sell", type=["numericColumn"],
                                             filter="agNumberColumnFilter", valueFormatter=days_fmt),
            },
            key="market_table",
        )

        st.write("")
        st.markdown("**Median price by model**")
        chart = table.head(40).dropna(subset=["median_price"]).copy()
        chart["name"] = (chart["brand"] + " " + chart["model"] + " · "
                         + chart["year_bucket"].astype(int).astype(str) + "–"
                         + (chart["year_bucket"].astype(int) + 1).astype(str))
        chart = chart.sort_values("median_price", ascending=False)
        render_bar_list(chart.to_dict("records"), lambda r: r["name"], lambda r: r["median_price"], money,
                         count_fn=lambda r: f'{int(r["n"])} ads')

        st.write("")
        st.markdown("**Fastest-selling models** (shorter bar = quicker flip)")
        liq_chart = table.dropna(subset=["median_days_to_sell"])
        liq_chart = liq_chart[liq_chart["sold_n"] >= 3].sort_values("median_days_to_sell").head(20).copy()
        if liq_chart.empty:
            st.caption("Not enough sold history yet to estimate days-to-sell (need ≥3 confirmed sales per model).")
        else:
            liq_chart["name"] = (liq_chart["brand"] + " " + liq_chart["model"] + " · "
                                 + liq_chart["year_bucket"].astype(int).astype(str) + "–"
                                 + (liq_chart["year_bucket"].astype(int) + 1).astype(str))
            render_bar_list(liq_chart.to_dict("records"), lambda r: r["name"], lambda r: r["median_days_to_sell"],
                             lambda v: f"{v:.0f}d", color="linear-gradient(90deg,#8a6a2c,#c99a3f)",
                             count_fn=lambda r: f'{int(r["sold_n"])} sold')

    st.write("")
    st.markdown("**Regional & fuel breakdown**")
    quality = ads_f[(ads_f["price"] > 100) & (~ads_f["is_blacklisted"].fillna(False))]
    b1, b2 = st.columns(2)
    with b1:
        st.caption("Median price by region")
        reg = quality.dropna(subset=["region"]).groupby("region")["price"].agg(["median", "count"]).reset_index()
        reg = reg[reg["count"] >= 3].sort_values("median", ascending=False).head(15)
        if reg.empty:
            st.caption("Not enough priced ads with region data for this selection.")
        else:
            render_bar_list(reg.to_dict("records"), lambda r: f'{r["region"]} ({int(r["count"])})',
                             lambda r: r["median"], money)
    with b2:
        st.caption("Median price by fuel")
        fu = quality.dropna(subset=["fuel"]).groupby("fuel")["price"].agg(["median", "count"]).reset_index()
        fu = fu[fu["count"] >= 3].sort_values("median", ascending=False).head(15)
        if fu.empty:
            st.caption("Not enough priced ads with fuel data for this selection.")
        else:
            render_bar_list(fu.to_dict("records"), lambda r: f'{r["fuel"]} ({int(r["count"])})',
                             lambda r: r["median"], money, color="linear-gradient(90deg,#5b4630,#a4502f)")

    st.write("")
    st.markdown("**Model deep-dive**")
    deep_opts = sorted(ads["brand"].dropna().unique()) if not ads.empty else []
    s1, s2, s3 = st.columns(3)
    sel_brand = s1.selectbox("Brand", deep_opts, key="market_deep_brand") if deep_opts else None
    pts = pd.DataFrame()
    if sel_brand:
        models = sorted(ads.loc[ads["brand"] == sel_brand, "model"].dropna().unique())
        sel_model = s2.selectbox("Model", models, key="market_deep_model") if models else None
        pts = ads[ads["brand"] == sel_brand]
        if sel_model:
            pts = pts[pts["model"] == sel_model]
            buckets = sorted(pts["year_bucket"].dropna().astype(int).unique())
            bucket_opts = ["All years"] + buckets
            sel_bucket = s3.selectbox(
                "Year", bucket_opts, key="market_deep_year",
                format_func=lambda b: b if b == "All years" else f"{b}–{b + 1}",
            ) if buckets else None
            if sel_bucket and sel_bucket != "All years":
                pts = pts[pts["year_bucket"] == sel_bucket]

    d1, d2 = st.columns(2)
    with d1:
        st.caption("Price vs. mileage")
        scatter_pts = pts.dropna(subset=["price", "mileage"])
        if scatter_pts.empty:
            st.caption("No ads with both price and mileage for this selection.")
        else:
            st.scatter_chart(scatter_pts, x="mileage", y="price", color="#1c3d2e", x_label="km", y_label="€")
    with d2:
        st.caption("Asking-price trend")
        if pts.empty:
            st.caption("Pick a brand above to see its price trend.")
        else:
            ph = load_price_history(tuple(sorted(pts["id"].dropna().astype(int).tolist())))
            if ph.empty:
                st.caption("No price history recorded yet for this selection.")
            else:
                ph = ph.copy()
                ph["seen_at"] = pd.to_datetime(ph["seen_at"], utc=True).dt.tz_localize(None)
                ph["week"] = ph["seen_at"].dt.to_period("W").dt.start_time
                trend = ph.groupby("week")["price"].median().reset_index()
                st.line_chart(trend, x="week", y="price", color="#1c3d2e", x_label="week", y_label="€ (median)")


def render_ads_tab():
    all_ads = load_all_ads()
    if all_ads.empty:
        st.info("No ads tracked yet.")
        return

    title_link_renderer = JsCode("""
        class TitleLinkRenderer {
            init(params) {
                this.eGui = document.createElement('span');
                this.eGui.style.display = 'inline-flex';
                this.eGui.style.alignItems = 'center';
                this.eGui.style.gap = '6px';
                const text = document.createElement('span');
                text.innerText = params.value || '';
                this.eGui.appendChild(text);
                if (params.data && params.data.url) {
                    const a = document.createElement('a');
                    a.href = params.data.url;
                    a.target = '_blank';
                    a.title = 'Open ad on OLX';
                    a.innerText = '\\u{1F517}';
                    a.style.textDecoration = 'none';
                    a.style.flexShrink = '0';
                    this.eGui.appendChild(a);
                }
            }
            getGui() { return this.eGui; }
        }
    """)
    render_filterable_table(
        all_ads[["title", "price", "brand", "model", "year", "mileage", "region", "url", "first_seen"]],
        column_config={
            "title": dict(cellRenderer=title_link_renderer, minWidth=260),
            "price": dict(type=["numericColumn"], filter="agNumberColumnFilter"),
            "year": dict(type=["numericColumn"], filter="agNumberColumnFilter"),
            "mileage": dict(type=["numericColumn"], filter="agNumberColumnFilter"),
            "url": dict(hide=True, filter=False),
        },
        key="ads_table",
        paginate=True,
    )


def render_detail(ad_id):
    row = deals[deals["ad_id"] == ad_id]
    if row.empty:
        st.session_state.open_id = None
        st.rerun()
        return
    d = row.iloc[0]

    if st.button("← Back to deals"):
        st.session_state.open_id = None
        st.rerun()

    verdict, vbg, vcolor = verdict_for(d["display_score"])
    gone = d.get("status") == "desaparecido"
    year = int(d["year"]) if pd.notna(d.get("year")) else "?"
    km = f"{int(d['mileage']):,}" if pd.notna(d.get("mileage")) else "?"

    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:18px;'
        f'flex-wrap:wrap;margin-top:10px">'
        f'<div><div style="display:flex;align-items:center;gap:9px;flex-wrap:wrap">'
        f'<span class="stand-badge" style="background:{vbg};color:{vcolor}">{verdict.upper()}</span>'
        + ('<span style="font-size:11px;color:#a4502f">👻 vanished — may be sold</span>' if gone else '') +
        f'</div><h1 style="font:500 27px \'Newsreader\',serif;color:#22201a;margin:12px 0 5px">'
        f'{esc(d["title"])}</h1>'
        f'<div style="font-size:13px;color:#8c856f">{year} · {km} km · {esc(d.get("fuel") or "?")} · '
        f'{esc(d.get("region") or "?")}</div></div>'
        f'<div style="text-align:center;flex:none">'
        f'<div style="font:600 40px \'Newsreader\',serif;color:{score_color(d["display_score"])};line-height:.9">'
        f'{d["display_score"]:.0f}</div>'
        f'<div class="stand-label" style="margin-top:2px">DEAL SCORE</div></div></div>',
        unsafe_allow_html=True,
    )

    if pd.notna(d.get("photo_url")):
        st.image(d["photo_url"], use_container_width=True)
    else:
        st.markdown(
            '<div style="width:100%;height:160px;border-radius:11px;margin:18px 0;'
            'background:repeating-linear-gradient(135deg,#eae2d0 0 11px,#e2d9c4 11px 22px);'
            'display:flex;align-items:center;justify-content:center;font:400 10px \'JetBrains Mono\',monospace;'
            'color:#a89e83">VEHICLE PHOTO</div>',
            unsafe_allow_html=True,
        )

    resale_value = d["median_price"] * config.RESALE_FACTOR
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            '<div class="stand-card">'
            '<div class="stand-label" style="margin-bottom:11px">THE FLIP MATH</div>'
            f'<div style="display:flex;justify-content:space-between;font-size:13px;color:#5b5647;padding:4px 0">'
            f'<span>Market median</span><span class="stand-mono">{money(d["median_price"])}</span></div>'
            f'<div style="display:flex;justify-content:space-between;font-size:13px;color:#5b5647;padding:4px 0">'
            f'<span>Resale @ {int(config.RESALE_FACTOR * 100)}%</span><span class="stand-mono">{money(resale_value)}</span></div>'
            f'<div style="display:flex;justify-content:space-between;font-size:13px;color:#5b5647;padding:4px 0">'
            f'<span>Ask price</span><span class="stand-mono">− {money(d["price"])}</span></div>'
            '<div style="height:1px;background:#e0d7c1;margin:8px 0"></div>'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline">'
            f'<span style="font-size:13px;font-weight:500;color:#22201a">Est. profit</span>'
            f'<span style="font:600 22px \'Newsreader\',serif;color:#2f6b47">{money(d["est_profit"])}</span></div>'
            '</div>',
            unsafe_allow_html=True,
        )
    with col2:
        p25, p75 = d.get("p25"), d.get("p75")
        if pd.isna(p25) or pd.isna(p75):
            p25, p75 = d["median_price"] * 0.86, d["median_price"] * 1.16

        def pos(v):
            return max(4, min(96, (v - p25) / (p75 - p25) * 100)) if p75 > p25 else 50

        st.markdown(
            '<div class="stand-card">'
            '<div class="stand-label" style="margin-bottom:14px">PRICE POSITION</div>'
            '<div style="position:relative;height:8px;border-radius:4px;'
            'background:linear-gradient(90deg,#3f8659,#e8c07a,#cf7a4e);margin:16px 4px 8px">'
            f'<div style="position:absolute;top:-14px;transform:translateX(-50%);left:{pos(d["median_price"]):.0f}%;'
            f'font:400 9px \'JetBrains Mono\',monospace;color:#8c856f">mkt</div>'
            f'<div style="position:absolute;top:-3px;width:2px;height:14px;background:#8c856f;'
            f'left:{pos(d["median_price"]):.0f}%"></div>'
            f'<div style="position:absolute;top:-4px;transform:translateX(-50%);left:{pos(d["price"]):.0f}%;'
            'width:15px;height:15px;border-radius:50%;background:#1c3d2e;border:2.5px solid #efeadd;'
            'box-shadow:0 1px 4px rgba(0,0,0,.25)"></div></div>'
            f'<div style="display:flex;justify-content:space-between;font-size:10px;color:#a09a84;padding:0 2px">'
            f'<span>{money(p25)}</span><span>{money(p75)}</span></div>'
            f'<div style="font-size:12px;line-height:1.5;color:#6a6454;margin-top:12px">This ask sits '
            f'<b style="color:#c99a3f">{d["discount"] * 100:.0f}% below</b> market median across '
            f'{int(d["n"]) if pd.notna(d.get("n")) else 0} comparable listings.</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    t1, t2, t3 = st.columns(3)
    conf_label, conf_color = CONF_META.get(d.get("confidence"), ("—", "#a09a84"))
    t1.markdown(
        f'<div class="stand-card"><div class="stand-label">TRUST</div>'
        f'<div style="display:flex;align-items:center;gap:7px;margin-top:7px">'
        f'<span style="width:9px;height:9px;border-radius:50%;background:{conf_color}"></span>'
        f'<span style="font:500 15px \'Newsreader\',serif;color:#22201a">{conf_label}</span></div>'
        f'<div style="font-size:11px;color:#8c856f;margin-top:3px">'
        f'{int(d["n"]) if pd.notna(d.get("n")) else 0} comparable ads</div></div>',
        unsafe_allow_html=True,
    )
    sell = d.get("median_days_to_sell")
    t2.markdown(
        f'<div class="stand-card"><div class="stand-label">LIQUIDITY</div>'
        f'<div style="font:500 15px \'Newsreader\',serif;color:#22201a;margin-top:7px">'
        f'{f"~{int(sell)} days" if pd.notna(sell) else "—"}</div>'
        f'<div style="font-size:11px;color:#8c856f;margin-top:3px">median time to sell</div></div>',
        unsafe_allow_html=True,
    )
    drop = d.get("price_drop")
    days = int(d["days_listed"]) if pd.notna(d.get("days_listed")) else 0
    listed_note = f'<span style="color:#a4502f">↓{money(drop)} recently</span>' if pd.notna(drop) else "price steady"
    t3.markdown(
        f'<div class="stand-card"><div class="stand-label">LISTED</div>'
        f'<div style="font:500 15px \'Newsreader\',serif;color:#22201a;margin-top:7px">{days} days</div>'
        f'<div style="font-size:11px;color:#8c856f;margin-top:3px">{listed_note}</div></div>',
        unsafe_allow_html=True,
    )

    st.write("")
    b1, b2, b3 = st.columns([2, 1, 1])
    is_fav = ad_id in fav_ids
    with b1:
        st.link_button("Open on OLX ↗", d["url"], use_container_width=True)
    with b2:
        if st.button("★ Favourited" if is_fav else "☆ Favourite", key=f"fav_detail_{ad_id}",
                      use_container_width=True):
            toggle_flag(ad_id, "favourite", is_fav)
            st.rerun()
    with b3:
        if st.button("Skip", key=f"skip_detail_{ad_id}", use_container_width=True):
            set_flag(ad_id, "skipped")
            st.session_state.open_id = None
            st.rerun()

    st.write("")
    st.markdown("**Similar Ads**")
    bucket = int(d["year_bucket"])
    fuel, mileage = d.get("fuel"), d.get("mileage")
    has_fuel = pd.notna(fuel)
    fine_basis = False
    mileage_lo = mileage_hi = None
    if has_fuel and pd.notna(mileage):
        # Mirrors evaluate()'s preference order (src/deal_engine.py) — if a fine
        # (fuel + mileage-band) match exists, that's the basis the stored median/n
        # used, so mileage-banded comps should match it too. Fuel itself is always
        # enforced below regardless of this match — different fuel types have
        # structurally different prices and are never "comparable".
        key = deal_engine.fine_key(d["brand"], d["model"], bucket, fuel, mileage)
        match = fine_stats[
            (fine_stats["brand"].str.lower() == key[0]) & (fine_stats["model"].str.lower() == key[1])
            & (fine_stats["year_bucket"] == key[2]) & (fine_stats["fuel"].str.lower() == key[3])
            & (fine_stats["km_band"] == key[4])
        ]
        if not match.empty:
            fine_basis = True
            band_lo = deal_engine.km_band(int(mileage))
            mileage_lo = band_lo
            mileage_hi = (config.KM_BANDS[0] if band_lo == 0
                          else (config.KM_BANDS[1] if band_lo == config.KM_BANDS[0] else None))
    comps = load_comps(
        d["brand"], d["model"], bucket, bucket + 1,
        fuel=fuel if has_fuel else None,
        mileage_lo=mileage_lo, mileage_hi=mileage_hi,
    ).dropna(subset=["price"])
    if ad_id not in comps["id"].values:
        # A just-crawled ad may not be reflected in the cached query yet — always
        # include it in its own comps so ranking/"THIS AD" is correct.
        comps = pd.concat([comps, pd.DataFrame([{
            "id": ad_id, "price": d["price"], "mileage": d.get("mileage"), "year": d.get("year"),
            "region": d.get("region"), "fuel": d.get("fuel"), "url": d["url"],
            "last_seen": d.get("last_seen"), "olx_created_at": d.get("olx_created_at"),
            "url_status": d.get("url_status"),
        }])], ignore_index=True)
    comps = comps.sort_values("price").reset_index(drop=True)
    if comps.empty:
        st.caption("No comparable ads currently tracked.")
    else:
        comps["rank"] = comps.index + 1
        self_rows = comps[comps["id"] == ad_id]
        self_rank = int(self_rows["rank"].iloc[0]) if not self_rows.empty else None
        if self_rank:
            basis_note = f", {esc(fuel)}" if has_fuel else ""
            st.caption(f"This ad ranks #{self_rank} cheapest of {len(comps)} comparable listings "
                       f"({d['brand']} {d['model']}, {bucket}–{bucket + 1}{basis_note})")
        for _, cm in comps.iterrows():
            is_self = cm["id"] == ad_id
            delta = cm["price"] - d["price"]
            delta_html = ""
            if not is_self:
                delta_color = "#2f6b47" if delta >= 0 else "#a4502f"
                delta_text = f"+{money(delta)}" if delta >= 0 else f"−{money(-delta)}"
                delta_html = f'<span style="font:500 12px \'JetBrains Mono\',monospace;color:{delta_color}">{delta_text}</span>'
            self_html = ('<span class="stand-badge" style="background:#1c3d2e;color:#e8c07a">THIS AD</span>'
                         if is_self else "")
            sold, days_to_sell = comp_sold_info(cm.get("last_seen"), cm.get("olx_created_at"), cm.get("url_status"))
            sold_text = f"SOLD · ~{int(days_to_sell)}d" if sold and days_to_sell is not None else "SOLD"
            sold_html = (f'<span class="stand-badge" style="background:#5c2b28;color:#e8b3a8">{sold_text}</span>'
                         if sold else "")
            row_bg = "#f2ecdc" if is_self else "#faf7ef"
            row_border = "#c99a3f" if is_self else "#e9e1cd"
            rank_color = "#c99a3f" if is_self else "#a09a84"
            fuel_bit = f' · {esc(cm["fuel"])}' if pd.notna(cm.get("fuel")) else ""
            km_val = f'{int(cm["mileage"]):,}' if pd.notna(cm.get("mileage")) else "?"
            year_val = int(cm["year"]) if pd.notna(cm.get("year")) else "?"
            st.markdown(
                f'<a href="{esc(cm["url"])}" target="_blank" style="display:flex;align-items:center;gap:12px;'
                f'flex-wrap:wrap;padding:11px 14px;border-radius:9px;background:{row_bg};'
                f'border:1px solid {row_border};text-decoration:none;color:inherit">'
                f'<span style="font:600 10px \'JetBrains Mono\',monospace;color:{rank_color};width:20px">'
                f'#{int(cm["rank"])}</span>'
                f'<span style="font:600 14px \'JetBrains Mono\',monospace;color:#22201a;width:80px">'
                f'{money(cm["price"])}</span>'
                f'<span style="font-size:12px;color:#6a6454">{km_val} km · {year_val} · '
                f'{esc(cm.get("region") or "?")}{fuel_bit}</span>'
                f'<span style="flex:1"></span>{sold_html}{self_html}{delta_html}'
                f'<span style="font-size:11px;color:#1c3d2e;text-decoration:underline">View ad ↗</span>'
                f'</a>',
                unsafe_allow_html=True,
            )


if st.session_state.open_id is not None:
    render_detail(st.session_state.open_id)
elif st.session_state.active_tab == "deals":
    render_deals_tab()
elif st.session_state.active_tab == "favourites":
    render_favourites_tab()
elif st.session_state.active_tab == "market":
    render_market_tab()
else:
    render_ads_tab()

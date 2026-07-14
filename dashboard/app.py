"""Streamlit dashboard. Run locally: streamlit run dashboard/app.py
Deploy free at https://share.streamlit.io (secrets: SUPABASE_URL, SUPABASE_KEY).
"""
import html
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

st.set_page_config(page_title="Stand · OLX Flip Radar", page_icon="🚗", layout="wide")

RESALE_FACTOR = 0.85
DEALS_PAGE_SIZE = 20
ADS_PAGE_SIZE = 200

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


@st.cache_data(ttl=120)
def load(table, order=None, limit=2000):
    q = sb().table(table).select("*")
    if order:
        q = q.order(order, desc=True)
    return pd.DataFrame(q.limit(limit).execute().data)


@st.cache_data(ttl=120)
def count_rows(table):
    return sb().table(table).select("id", count="exact").limit(1).execute().count


@st.cache_data(ttl=120)
def load_ads_page(offset, limit):
    q = sb().table("ads").select("*").order("first_seen", desc=True)
    return pd.DataFrame(q.range(offset, offset + limit - 1).execute().data)


def minutes_since(ts: str) -> float:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).total_seconds() / 60


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
</style>
""", unsafe_allow_html=True)

st.session_state.setdefault("active_tab", "deals")
st.session_state.setdefault("skipped_ids", set())
st.session_state.setdefault("open_id", None)

deals = load("deals_view", order="created_at")
ads = load("ads", order="first_seen", limit=5000)
runs = load("crawl_runs", order="started_at", limit=1)
stats = load("market_stats")
liq = load("market_liquidity")

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

TABS = [("deals", "Deals"), ("market", "Market"), ("ads", "Ads")]
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


def render_deals_tab():
    if deals.empty:
        st.info("No deals yet — the crawler needs a few runs to build market stats.")
        return

    profit_lo, profit_hi = int(deals["est_profit"].min()), int(deals["est_profit"].max())
    if profit_lo == profit_hi:
        profit_hi += 1
    km_series = deals["mileage"].dropna()
    km_lo, km_hi = (int(km_series.min()), int(km_series.max())) if not km_series.empty else (0, 300_000)
    if km_lo == km_hi:
        km_hi += 1
    year_series = deals["year"].dropna()
    year_lo, year_hi = (int(year_series.min()), int(year_series.max())) if not year_series.empty else (1980, 2030)
    if year_lo == year_hi:
        year_hi += 1

    with st.container(border=True):
        f1, f2, f3 = st.columns(3)
        min_profit, max_profit = f1.slider("PROFIT (€)", profit_lo, profit_hi, (profit_lo, profit_hi), step=10)
        min_km, max_km = f2.slider("MILEAGE (KM)", km_lo, km_hi, (km_lo, km_hi), step=1000)
        min_year, max_year = f3.slider("YEAR", year_lo, year_hi, (year_lo, year_hi))
        f4, f5, f6, f7 = st.columns(4)
        brand_opts = sorted(deals["brand"].dropna().unique())
        brand = f4.selectbox("BRAND", ["All brands"] + brand_opts)
        region_opts = sorted(deals["region"].dropna().unique())
        region = f5.selectbox("REGION", ["All regions"] + region_opts)
        conf = f6.selectbox("TRUST", ["All levels", "alta", "media", "baixa"],
                             format_func=lambda c: c if c == "All levels" else CONF_META[c][0])
        only_active = f7.checkbox("Active listings only", value=True)

    view = deals[~deals["ad_id"].isin(st.session_state.skipped_ids)]
    view = view[(view["est_profit"] >= min_profit) & (view["est_profit"] <= max_profit)]
    view = view[view["mileage"].isna() | view["mileage"].between(min_km, max_km)]
    view = view[view["year"].isna() | view["year"].between(min_year, max_year)]
    if brand != "All brands":
        view = view[view["brand"] == brand]
    if region != "All regions":
        view = view[view["region"] == region]
    if conf != "All levels":
        view = view[view["confidence"] == conf]
    if only_active and "status" in view:
        view = view[view["status"] == "ativo"]

    skipped = st.session_state.skipped_ids
    with st.container(border=True):
        s1, s2, s3, s4 = st.columns([1, 1, 1, 1])
        s1.metric("LIVE DEALS", len(view))
        s2.metric("TOTAL EST. PROFIT", money(view["est_profit"].sum()) if len(view) else "—")
        s3.metric("AVG DISCOUNT", f"{view['discount'].mean() * 100:.0f}%" if len(view) else "—")
        with s4:
            if skipped:
                st.caption(f"{len(skipped)} skipped")
                if st.button("Undo all", key="undo_all"):
                    st.session_state.skipped_ids = set()
                    st.rerun()

    view = view.sort_values("score", ascending=False)
    total_pages = max(1, -(-len(view) // DEALS_PAGE_SIZE))

    st.write("")
    page = pagination_controls("deals_page", total_pages)
    start = (page - 1) * DEALS_PAGE_SIZE
    st.write("")
    for _, d in view.iloc[start:start + DEALS_PAGE_SIZE].iterrows():
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
                if st.button("Open", key=f"open_{d['ad_id']}", use_container_width=True):
                    st.session_state.open_id = int(d["ad_id"])
                    st.rerun()
                if st.button("Skip", key=f"skip_{d['ad_id']}", use_container_width=True):
                    st.session_state.skipped_ids = st.session_state.skipped_ids | {int(d["ad_id"])}
                    st.rerun()

    st.write("")
    pagination_controls("deals_page", total_pages, widget_key="deals_page_bottom")


def render_market_tab():
    if stats.empty:
        st.info("Market stats appear once ≥5 comparable ads exist per model.")
        return

    display = stats.merge(liq, on=["brand", "model", "year_bucket"], how="left") if not liq.empty else stats.copy()

    sort_options = {
        "Sample size (N)": "n",
        "Median price": "median_price",
        "Active listings": "active_ads",
        "Days to sell": "median_days_to_sell",
        "Model": ["brand", "model"],
    }
    sc1, sc2 = st.columns([3, 1])
    sort_label = sc1.selectbox("SORT BY", list(sort_options.keys()))
    descending = sc2.checkbox("Descending", value=True)
    display = display.sort_values(sort_options[sort_label], ascending=not descending, na_position="last")
    total_models = len(display)
    display = display.head(40)

    st.caption(f"Market snapshot across {total_models} tracked models (showing top {len(display)} by {sort_label.lower()}) · "
               f"medians need ≥5 comparable ads in the last 90 days")

    with st.container(border=True):
        h = st.columns([2, 1, 0.7, 1, 1.3, 1, 1.2])
        for col, label in zip(h, ["MODEL", "YEAR BUCKET", "N", "MEDIAN", "RANGE (P25–P75)", "ACTIVE", "DAYS TO SELL"]):
            col.markdown(f'<span class="stand-label">{label}</span>', unsafe_allow_html=True)
        for _, m in display.iterrows():
            bucket = int(m["year_bucket"])
            row = st.columns([2, 1, 0.7, 1, 1.3, 1, 1.2])
            row[0].markdown(f'<span class="stand-row-title">{esc(m["brand"])} {esc(m["model"])}</span>',
                             unsafe_allow_html=True)
            row[1].markdown(f'<span class="stand-mono">{bucket}–{bucket + 1}</span>', unsafe_allow_html=True)
            row[2].markdown(f'<span class="stand-mono">{int(m["n"])}</span>', unsafe_allow_html=True)
            row[3].markdown(f'<span class="stand-mono">{money(m["median_price"])}</span>', unsafe_allow_html=True)
            row[4].markdown(f'<span class="stand-mono">{money(m["p25"])} – {money(m["p75"])}</span>',
                             unsafe_allow_html=True)
            active = m.get("active_ads")
            row[5].markdown(f'<span class="stand-mono">{int(active) if pd.notna(active) else "—"}</span>',
                             unsafe_allow_html=True)
            sell = m.get("median_days_to_sell")
            row[6].markdown(f'<span class="stand-mono">{f"~{int(sell)}d" if pd.notna(sell) else "—"}</span>',
                             unsafe_allow_html=True)

    st.write("")
    st.markdown("**Median price by model**")
    chart = display.dropna(subset=["median_price"]).copy()
    chart["name"] = (chart["brand"] + " " + chart["model"] + " · "
                     + chart["year_bucket"].astype(int).astype(str) + "–"
                     + (chart["year_bucket"].astype(int) + 1).astype(str))
    chart = chart.sort_values("median_price", ascending=False)
    max_median = chart["median_price"].max()
    for _, c in chart.iterrows():
        pct = c["median_price"] / max_median * 100 if max_median else 0
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">'
            f'<span style="width:220px;flex:none;font-size:12px;color:#5b5647;overflow:hidden;'
            f'text-overflow:ellipsis;white-space:nowrap">{esc(c["name"])}</span>'
            f'<div style="flex:1;height:16px;background:#e8dfca;border-radius:4px;overflow:hidden">'
            f'<div style="height:100%;background:linear-gradient(90deg,#1c3d2e,#3f8659);width:{pct:.0f}%"></div></div>'
            f'<span style="width:70px;flex:none;text-align:right;font:500 12px \'JetBrains Mono\',monospace">'
            f'{money(c["median_price"])}</span></div>',
            unsafe_allow_html=True,
        )

    st.write("")
    st.markdown("**Price vs. mileage**")
    brand_opts = sorted(ads["brand"].dropna().unique()) if not ads.empty else []
    s1, s2 = st.columns(2)
    sel_brand = s1.selectbox("Brand", brand_opts) if brand_opts else None
    if sel_brand:
        models = sorted(ads.loc[ads["brand"] == sel_brand, "model"].dropna().unique())
        sel_model = s2.selectbox("Model", models) if models else None
        pts = ads[ads["brand"] == sel_brand]
        if sel_model:
            pts = pts[pts["model"] == sel_model]
        pts = pts.dropna(subset=["price", "mileage"])
        if pts.empty:
            st.caption("No ads with both price and mileage for this selection.")
        else:
            st.scatter_chart(pts, x="mileage", y="price", color="#1c3d2e", x_label="km", y_label="€")


def render_ads_tab():
    total_ads = count_rows("ads") or 0
    if not total_ads:
        st.info("No ads tracked yet.")
        return

    total_pages = max(1, -(-total_ads // ADS_PAGE_SIZE))
    page = pagination_controls("ads_page", total_pages)
    page_ads = load_ads_page((page - 1) * ADS_PAGE_SIZE, ADS_PAGE_SIZE)

    st.dataframe(
        page_ads[["title", "price", "brand", "model", "year", "mileage", "region", "url", "first_seen"]],
        use_container_width=True, hide_index=True, height=700,
        column_config={"url": st.column_config.LinkColumn("link")},
    )
    st.write("")
    pagination_controls("ads_page", total_pages, widget_key="ads_page_bottom")


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

    resale_value = d["median_price"] * RESALE_FACTOR
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            '<div class="stand-card">'
            '<div class="stand-label" style="margin-bottom:11px">THE FLIP MATH</div>'
            f'<div style="display:flex;justify-content:space-between;font-size:13px;color:#5b5647;padding:4px 0">'
            f'<span>Market median</span><span class="stand-mono">{money(d["median_price"])}</span></div>'
            f'<div style="display:flex;justify-content:space-between;font-size:13px;color:#5b5647;padding:4px 0">'
            f'<span>Resale @ {int(RESALE_FACTOR * 100)}%</span><span class="stand-mono">{money(resale_value)}</span></div>'
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
    b1, b2 = st.columns([3, 1])
    with b1:
        st.link_button("Open on OLX ↗", d["url"], use_container_width=True)
    with b2:
        if st.button("Skip", key=f"skip_detail_{ad_id}", use_container_width=True):
            st.session_state.skipped_ids = st.session_state.skipped_ids | {int(ad_id)}
            st.session_state.open_id = None
            st.rerun()

    st.write("")
    st.markdown("**Similar Ads**")
    bucket = int(d["year_bucket"])
    comps = ads[
        (ads["brand"] == d["brand"]) & (ads["model"] == d["model"])
        & ((ads["year"] // 2 * 2) == bucket)
    ].dropna(subset=["price"])
    if ad_id not in comps["id"].values:
        # The opened ad may fall outside the ads dataframe's 5000-row cap (ordered by
        # first_seen) — always include it in its own comps so ranking/"THIS AD" is correct.
        comps = pd.concat([comps, pd.DataFrame([{
            "id": ad_id, "price": d["price"], "mileage": d.get("mileage"), "year": d.get("year"),
            "region": d.get("region"), "fuel": d.get("fuel"), "url": d["url"],
        }])], ignore_index=True)
    comps = comps.sort_values("price").reset_index(drop=True)
    if comps.empty:
        st.caption("No comparable ads currently tracked.")
    else:
        comps["rank"] = comps.index + 1
        self_rows = comps[comps["id"] == ad_id]
        self_rank = int(self_rows["rank"].iloc[0]) if not self_rows.empty else None
        if self_rank:
            st.caption(f"This ad ranks #{self_rank} cheapest of {len(comps)} comparable listings "
                       f"({d['brand']} {d['model']}, {bucket}–{bucket + 1})")
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
                f'<span style="flex:1"></span>{self_html}{delta_html}'
                f'<span style="font-size:11px;color:#1c3d2e;text-decoration:underline">View ad ↗</span>'
                f'</a>',
                unsafe_allow_html=True,
            )


if st.session_state.open_id is not None:
    render_detail(st.session_state.open_id)
elif st.session_state.active_tab == "deals":
    render_deals_tab()
elif st.session_state.active_tab == "market":
    render_market_tab()
else:
    render_ads_tab()

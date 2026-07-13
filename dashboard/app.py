"""Streamlit dashboard. Run locally: streamlit run dashboard/app.py
Deploy free at https://share.streamlit.io (secrets: SUPABASE_URL, SUPABASE_KEY).
"""
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

st.set_page_config(page_title="OLX Car Deals", page_icon="🚗", layout="wide")

CHART_COLOR = "#4269d0"
CONF_BADGE = {"alta": "🟢 alta", "media": "🟡 média", "baixa": "🔴 baixa"}


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


def minutes_since(ts: str) -> float:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).total_seconds() / 60


st.title("🚗 OLX.pt Car Deal Finder")

deals = load("deals_view", order="created_at")
ads = load("ads", order="first_seen", limit=5000)
runs = load("crawl_runs", order="started_at", limit=1)

if runs.empty:
    st.warning("Sem registos de recolha — o crawler ainda não correu com o esquema novo.")
else:
    mins = minutes_since(runs.iloc[0]["started_at"])
    msg = f"Última recolha: há {mins:.0f} min ({runs.iloc[0]['mode']})"
    if mins > 120:
        st.error(f"⚠️ {msg} — dados possivelmente desatualizados")
    else:
        st.caption(f"🕒 {msg}")

active_deals = deals[deals["status"] == "ativo"] if "status" in deals else deals

c1, c2, c3, c4 = st.columns(4)
c1.metric("Ads tracked", f"{count_rows('ads') or 0:,}")
c2.metric("Deals found", len(deals), help=f"{len(active_deals)} ainda ativos")
c3.metric("Best est. profit (ativos)",
          f"€{active_deals['est_profit'].max():,.0f}" if len(active_deals) else "—")
c4.metric("Avg discount",
          f"{deals['discount'].mean() * 100:.0f}%" if len(deals) else "—")

tab_deals, tab_ads, tab_market = st.tabs(["💰 Deals", "📋 Recent ads", "📊 Market"])

with tab_deals:
    if deals.empty:
        st.info("No deals yet — the crawler needs a few runs to build market stats.")
    else:
        f1, f2, f3, f4 = st.columns(4)
        min_profit = f1.slider("Lucro mín. estimado (€)", 0, 2000, 300, 50)
        brands = f2.multiselect("Marca", sorted(deals["brand"].dropna().unique()))
        regions = f3.multiselect("Região", sorted(deals["region"].dropna().unique()))
        confs = f4.multiselect("Confiança", ["alta", "media", "baixa"],
                               format_func=lambda c: CONF_BADGE[c])
        f5, f6, f7 = st.columns(3)
        max_km = f5.number_input("Km máx.", 0, 500_000, 300_000, 10_000)
        min_year = f6.number_input("Ano mín.", 1980, 2030, 2000)
        only_active = f7.checkbox("Só anúncios ativos", value=True)

        view = deals[deals["est_profit"] >= min_profit]
        if brands:
            view = view[view["brand"].isin(brands)]
        if regions:
            view = view[view["region"].isin(regions)]
        if confs:
            view = view[view["confidence"].isin(confs)]
        view = view[view["mileage"].fillna(0) <= max_km]
        view = view[view["year"].fillna(9999) >= min_year]
        if only_active and "status" in view:
            view = view[view["status"] == "ativo"]

        st.caption(f"{len(view)} negócio(s)")
        for _, d in view.sort_values("score", ascending=False).iterrows():
            with st.container(border=True):
                cols = st.columns([1, 3, 1])
                if pd.notna(d.get("photo_url")):
                    cols[0].image(d["photo_url"], use_container_width=True)
                info = cols[1]
                info.markdown(f"**[{d['title']}]({d['url']})**")
                km = f"{int(d['mileage']):,}" if pd.notna(d.get("mileage")) else "?"
                year = int(d["year"]) if pd.notna(d.get("year")) else "?"
                fuel = d["fuel"] if pd.notna(d.get("fuel")) else "?"
                region = d["region"] if pd.notna(d.get("region")) else "?"
                info.caption(f"{d['brand']} {d['model']} · {year} · "
                             f"{km} km · {fuel} · {region}")
                conf = d.get("confidence")
                badges = [CONF_BADGE.get(conf, "⚪ sem confiança")]
                if pd.notna(d.get("n")):
                    badges.append(f"{int(d['n'])} comparáveis")
                if d.get("status") == "desaparecido":
                    badges.append("👻 desaparecido (vendido?)")
                if pd.notna(d.get("days_listed")):
                    badges.append(f"{int(d['days_listed'])} dias anunciado")
                if pd.notna(d.get("price_drop")):
                    badges.append(f"📉 baixou €{d['price_drop']:,.0f}")
                info.caption(" · ".join(badges))
                cols[2].metric(f"€{d['price']:,.0f}",
                               f"+€{d['est_profit']:,.0f} est.",
                               help=f"Mediana €{d['median_price']:,.0f} "
                                    f"({d['discount'] * 100:.0f}% abaixo)")

with tab_ads:
    if not ads.empty:
        st.dataframe(
            ads[["title", "price", "brand", "model", "year", "mileage",
                 "region", "url", "first_seen"]],
            use_container_width=True, hide_index=True,
            column_config={"url": st.column_config.LinkColumn("link")},
        )

with tab_market:
    stats = load("market_stats")
    if stats.empty:
        st.info("Market stats appear once ≥5 comparable ads exist per model.")
    else:
        liq = load("market_liquidity")
        if not liq.empty:
            stats = stats.merge(liq, on=["brand", "model", "year_bucket"], how="left")
        st.dataframe(stats.sort_values("n", ascending=False),
                     use_container_width=True, hide_index=True,
                     column_config={
                         "median_days_to_sell": st.column_config.NumberColumn(
                             "dias até vender (mediana)", format="%.0f"),
                         "active_ads": "anúncios ativos",
                     })

        st.subheader("Preço vs. quilómetros")
        s1, s2 = st.columns(2)
        brand_opts = sorted(ads["brand"].dropna().unique()) if not ads.empty else []
        sel_brand = s1.selectbox("Marca", brand_opts) if brand_opts else None
        if sel_brand:
            models = sorted(ads.loc[ads["brand"] == sel_brand, "model"].dropna().unique())
            sel_model = s2.selectbox("Modelo", models) if models else None
            pts = ads[(ads["brand"] == sel_brand)]
            if sel_model:
                pts = pts[pts["model"] == sel_model]
            pts = pts.dropna(subset=["price", "mileage"])
            if pts.empty:
                st.caption("Sem anúncios com preço e km para esta seleção.")
            else:
                st.scatter_chart(pts, x="mileage", y="price", color=CHART_COLOR,
                                 x_label="km", y_label="€")

        st.subheader("Mediana de preço por marca (top 20)")
        top = (ads.dropna(subset=["brand"]).groupby("brand")["price"]
               .median().sort_values(ascending=False).head(20))
        st.bar_chart(top, color=CHART_COLOR, x_label="", y_label="€ (mediana)")

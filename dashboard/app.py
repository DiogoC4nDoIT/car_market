"""Streamlit dashboard. Run locally: streamlit run dashboard/app.py
Deploy free at https://share.streamlit.io (secrets: SUPABASE_URL, SUPABASE_KEY).
"""
import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

st.set_page_config(page_title="OLX Car Deals", page_icon="🚗", layout="wide")


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


st.title("🚗 OLX.pt Car Deal Finder")

deals = load("deals_view", order="created_at")
ads = load("ads", order="first_seen", limit=5000)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Ads tracked", f"{len(ads):,}")
c2.metric("Deals found", len(deals))
c3.metric("Best est. profit", f"€{deals['est_profit'].max():,.0f}" if len(deals) else "—")
c4.metric("Avg discount", f"{deals['discount'].mean() * 100:.0f}%" if len(deals) else "—")

tab_deals, tab_ads, tab_market = st.tabs(["💰 Deals", "📋 Recent ads", "📊 Market"])

with tab_deals:
    if deals.empty:
        st.info("No deals yet — the crawler needs a few runs to build market stats.")
    else:
        f1, f2 = st.columns(2)
        min_profit = f1.slider("Min. estimated profit (€)", 0, 2000, 300, 50)
        brands = f2.multiselect("Brand", sorted(deals["brand"].dropna().unique()))
        view = deals[deals["est_profit"] >= min_profit]
        if brands:
            view = view[view["brand"].isin(brands)]
        for _, d in view.sort_values("score", ascending=False).iterrows():
            with st.container(border=True):
                a, b = st.columns([3, 1])
                a.markdown(f"**[{d['title']}]({d['url']})**")
                a.caption(
                    f"{d['brand']} {d['model']} · {d['year']} · "
                    f"{d['mileage'] or '?'} km · {d['fuel'] or '?'} · {d['region'] or '?'}"
                )
                b.metric(f"€{d['price']:,.0f}",
                         f"+€{d['est_profit']:,.0f} est.",
                         help=f"Market median €{d['median_price']:,.0f} "
                              f"({d['discount'] * 100:.0f}% below)")

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
        st.dataframe(stats.sort_values("n", ascending=False),
                     use_container_width=True, hide_index=True)
        top = (ads.dropna(subset=["brand"]).groupby("brand")["price"]
               .median().sort_values(ascending=False).head(20))
        st.bar_chart(top)

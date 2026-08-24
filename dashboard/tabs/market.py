from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from st_aggrid.shared import JsCode

from src import config
from dashboard.components import render_bar_list, render_filterable_table
from dashboard.context import Context
from dashboard.data import count_ads, load_price_history
from dashboard.format_utils import money


def render_market_tab(ctx: Context):
    stats, ads, liq = ctx.stats, ctx.ads, ctx.liq
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
        top = st.columns([8, 1])
        with top[1]:
            if st.button("↺ Reset", key="market_reset_filters", use_container_width=True,
                         help="Clear all Market filters"):
                for k in ("market_filter_brand", "market_filter_region", "market_filter_fuel",
                          "market_filter_year", "market_filter_price"):
                    st.session_state.pop(k, None)
                st.rerun()
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
    stats_f = (ctx.fuel_stats[ctx.fuel_stats["fuel"] == fuel].drop(columns="fuel").copy()
               if fuel != "All fuels" and not ctx.fuel_stats.empty else stats.copy())
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
    week_cutoff = (now_ts - timedelta(days=7)).isoformat()
    active_cutoff = (now_ts - timedelta(days=config.ACTIVE_WINDOW_DAYS)).isoformat()
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

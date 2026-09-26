from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from st_aggrid.shared import JsCode

from src import config, deal_engine
from dashboard import ai_brief
from dashboard.components import render_bar_list, render_filterable_table
from dashboard.context import Context
from dashboard.data import count_ads, load_price_history
from dashboard.format_utils import CONF_META, money

RATING_COLORS = {
    "Great deal": "linear-gradient(90deg,var(--success-dark),var(--success-main))",
    "Good deal": "linear-gradient(90deg,var(--success-main),var(--success-light))",
    "Fair price": "linear-gradient(90deg,var(--info-dark),var(--info-main))",
    "High price": "linear-gradient(90deg,var(--warning-dark),var(--warning-main))",
    "Overpriced": "linear-gradient(90deg,var(--error-dark),var(--error-main))",
}


def _km_band_label(mileage) -> str:
    """Human mileage-band phrasing matching config.KM_BANDS / deal_engine.km_band() —
    lets the AI brief say 'under 150k km' instead of a bare, uncontextualized number."""
    lo, hi = config.KM_BANDS
    if mileage < lo:
        return f"under {lo // 1000}k km"
    if mileage < hi:
        return f"{lo // 1000}k–{hi // 1000}k km"
    return f"over {hi // 1000}k km"


def _price_cut_rollup(ads: pd.DataFrame) -> pd.DataFrame:
    """Per brand/model/year-bucket price-cut activity, from price_history for the
    (already 5,000-capped) `ads` sample — no extra Supabase load beyond what's already
    cached, same sampling caveat as the regional/fuel breakdown below."""
    ids = tuple(sorted(ads["id"].dropna().astype(int).tolist()))
    ph = load_price_history(ids)
    cols = ["brand", "model", "year_bucket", "pct_price_cut", "avg_days_since_cut"]
    if ph.empty:
        return pd.DataFrame(columns=cols)
    ph = ph.copy()
    ph["seen_at"] = pd.to_datetime(ph["seen_at"], utc=True)
    ph = ph.sort_values(["ad_id", "seen_at"])
    per_ad = ph.groupby("ad_id").agg(first_price=("price", "first"), last_price=("price", "last"),
                                      last_seen=("seen_at", "max"))
    per_ad["price_cut"] = per_ad["last_price"] < per_ad["first_price"]
    per_ad = per_ad.merge(
        ads[["id", "brand", "model", "year_bucket"]].rename(columns={"id": "ad_id"}),
        on="ad_id", how="inner",
    )
    now_ts = pd.Timestamp.now(tz="UTC")
    per_ad["days_since_seen"] = (now_ts - per_ad["last_seen"]).dt.total_seconds() / 86400
    grouped = per_ad.groupby(["brand", "model", "year_bucket"])
    out = grouped["price_cut"].agg(["mean", "count"]).rename(columns={"mean": "pct_price_cut", "count": "n_hist"})
    out["avg_days_since_cut"] = per_ad[per_ad["price_cut"]].groupby(
        ["brand", "model", "year_bucket"])["days_since_seen"].mean()
    # Needs >=3 ads with price history behind it, same minimum-sample bar as the
    # fastest-selling chart below, so a single ad's price cut doesn't read as a trend.
    out.loc[out["n_hist"] < 3, ["pct_price_cut", "avg_days_since_cut"]] = None
    return out.reset_index()[cols]


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
            if st.button("Reset", icon=":material/refresh:", key="market_reset_filters", use_container_width=True,
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
    cut_cols = ["pct_price_cut", "avg_days_since_cut"]
    if not ads.empty:
        display = display.merge(_price_cut_rollup(ads), on=["brand", "model", "year_bucket"], how="left")
    for col in cut_cols:
        if col not in display:
            display[col] = None
    # Market Days Supply: how many days it'd take to sell off the current active listings
    # at the last-60-days sell-through rate — vAuto's "Market Days Supply", the dealer-world
    # metric for spotting an oversupplied (avoid sourcing) vs. scarce (safe to source) model.
    # Needs >=3 sales in the window or the rate is too noisy to trust. sold_n_60d only exists
    # once supabase_schema.sql's market_liquidity update has been (re-)run — falls back to
    # an all-null column until then instead of crashing the table below.
    display["mds"] = None
    if "sold_n_60d" in display and "active_ads" in display:
        enough = display["sold_n_60d"].fillna(0) >= 3
        display.loc[enough, "mds"] = (
            display.loc[enough, "active_ads"].astype(float) / display.loc[enough, "sold_n_60d"] * 60
        )
    else:
        display["sold_n_60d"] = None
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

    st.write("")
    st.markdown("**AI good-deal brief** (optional, free)")
    if not ai_brief.available():
        st.caption("Set GROQ_API_KEY (free tier at console.groq.com) in secrets/.env to turn on a "
                   "short AI summary of the best deals matching your filters above — every other "
                   "Market tab feature works without it.")
    elif ctx.deals.empty:
        st.caption("No deals tracked yet.")
    else:
        # Driven entirely by the filter bar above (brand/region/fuel/year/price) — NOT by the
        # Model deep-dive's own selectors further down, which scope a different, single-model
        # set of charts. `ctx.deals` is deal_engine.evaluate()'s own output (already vetted on
        # budget/discount/profit/mileage/blacklist together — the same bar that drives the Deals
        # tab and Telegram alerts), filtered active-only so nothing delisted gets recommended.
        deals_f = ctx.deals[ctx.deals["status"] == "ativo"].copy()
        if brand != "All brands":
            deals_f = deals_f[deals_f["brand"] == brand]
        if region != "All regions":
            deals_f = deals_f[deals_f["region"] == region]
        if fuel != "All fuels":
            deals_f = deals_f[deals_f["fuel"] == fuel]
        deals_f = deals_f[deals_f["year"].isna() | deals_f["year"].between(yr_lo, yr_hi)]
        deals_f = deals_f[deals_f["price"].between(p_lo, p_hi)]

        # Skipped ads stay in the candidate pool for comparison purposes (near-miss counts,
        # regional-arbitrage stats below) but must never be surfaced as a suggestion — the user
        # already dismissed them once.
        deals_f_all = deals_f
        deals_f = deals_f[~deals_f["ad_id"].isin(ctx.skipped_ids)]

        total_matches = int(len(deals_f))
        if total_matches == 0:
            st.caption("No vetted deals (passing the crawler's budget/discount/profit/mileage bar) "
                       "match these filters right now — try widening the price range or region.")
        else:
            top = deals_f.sort_values("score", ascending=False).head(5).copy()
            top["label"] = top.apply(
                lambda r: f"{r['brand']} {r['model']} ({int(r['year']) if pd.notna(r['year']) else '?'}) "
                          f"· {money(r['price'])}",
                axis=1,
            )

            # Near-miss count: ads matching the same filters that are cheap vs. their OWN median
            # (deal_rating Great/Good) but never made it into `deals` — i.e. failed the budget/
            # profit/mileage/blacklist bar. Reported separately, never blended into the deal list:
            # a below-median ad that doesn't clear that bar isn't one a flipper can act on, however
            # good it looks by price-vs-median alone.
            near_miss_count = None
            good_ads = ads_f[~ads_f["is_blacklisted"].fillna(False)].dropna(
                subset=["price", "year", "brand", "model"])
            if not good_ads.empty and not stats.empty:
                stats_idx_top = deal_engine.build_stats_index(stats.to_dict("records"))

                def _rating_top(row):
                    st_ = stats_idx_top.get(deal_engine.stats_key(row["brand"], row["model"], row["year"]))
                    if not st_ or not st_.get("median_price"):
                        return None
                    return deal_engine.deal_rating(1 - row["price"] / float(st_["median_price"]))

                good_ratings = good_ads.apply(_rating_top, axis=1)
                good_ids = set(good_ads.loc[good_ratings.isin(["Great deal", "Good deal"]), "id"])
                # Compare against deals_f_all (skip-inclusive) so a deal the user already skipped
                # doesn't get double-counted as a "near miss" too — it already cleared the bar.
                near_miss_count = len(good_ids - set(deals_f_all["ad_id"])) or None

            # Regional-arbitrage aside: where the models actually surfaced clear elsewhere, so a
            # region filter doesn't silently hide the cross-region spread the crawler exists to find.
            arb_pool = ctx.deals[ctx.deals["status"] == "ativo"]
            if brand != "All brands":
                arb_pool = arb_pool[arb_pool["brand"] == brand]
            if fuel != "All fuels":
                arb_pool = arb_pool[arb_pool["fuel"] == fuel]
            arb_pool = arb_pool[arb_pool["brand"].isin(top["brand"]) & arb_pool["model"].isin(top["model"])]
            region_counts = arb_pool.dropna(subset=["region"]).groupby("region").agg(
                median=("price", "median"), count=("price", "size"))
            region_counts = region_counts[region_counts["count"] >= 2].sort_values("count", ascending=False).head(5)
            region_breakdown = {
                r: {"median_eur": round(float(row["median"])), "count": int(row["count"])}
                for r, row in region_counts.iterrows()
            } or None

            deals_payload = [{
                "label": r["label"],
                "price_eur": int(r["price"]),
                "median_eur": round(float(r["median_price"])) if pd.notna(r["median_price"]) else None,
                "discount_pct": round(float(r["discount"]) * 100) if pd.notna(r["discount"]) else None,
                "est_profit_eur": round(float(r["est_profit"])) if pd.notna(r["est_profit"]) else None,
                "confidence": CONF_META.get(r["confidence"], (r["confidence"],))[0],
                "n_comps": int(r["n"]) if pd.notna(r["n"]) else None,
                "mileage_km": int(r["mileage"]) if pd.notna(r["mileage"]) else None,
                "km_band": _km_band_label(r["mileage"]) if pd.notna(r["mileage"]) else None,
                "region": r["region"] if pd.notna(r["region"]) else None,
                "fuel": r["fuel"] if pd.notna(r["fuel"]) else None,
                "days_listed": int(r["days_listed"]) if pd.notna(r.get("days_listed")) else None,
                "price_drop_eur": round(float(r["price_drop"])) if pd.notna(r.get("price_drop")) else None,
            } for _, r in top.iterrows()]

            summary = {
                "total_matches": total_matches,
                "shown": len(deals_payload),
                "near_miss_count": near_miss_count,
                "region_breakdown": region_breakdown,
                "deals": deals_payload,
            }
            summary = {k: v for k, v in summary.items() if v not in (None, {}, [])}

            # Filter/count line is rendered here, not by the LLM — a free-tier 20B model at low
            # reasoning effort proved unreliable at echoing a specific number back out of a nested
            # dict (verified: it substituted the dataset's 15,000 max for an actual 2,201 filter
            # despite an explicit "quote digit for digit" instruction). Anything the app can state
            # deterministically, it should — the model's job is narrating the deals, not formatting
            # numbers it was just handed.
            filter_bits = [brand if brand != "All brands" else None, region if region != "All regions" else None,
                           fuel if fuel != "All fuels" else None, f"{yr_lo}–{yr_hi}", f"up to {money(p_hi)}"]
            st.caption(f"Filters: {' · '.join(b for b in filter_bits if b)} — "
                       f"top {len(deals_payload)} of {total_matches} vetted deals, ranked by score.")

            if st.button("Generate brief", key="ai_brief_btn", icon=":material/auto_awesome:"):
                with st.spinner("Asking the model..."):
                    brief = ai_brief.generate_brief(summary)
                if brief:
                    st.info(brief)
                    st.caption("Real listings referenced above (not AI-generated links):")
                    for _, r in top.iterrows():
                        st.markdown(f"- **{r['label']}** — [{r['title']}]({r['url']}) · "
                                    f"[View in Stand](?ad={int(r['ad_id'])})")
                else:
                    st.caption("Couldn't generate a brief right now — check GROQ_API_KEY and try again.")

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
        pct_fmt = JsCode("function(p){return p.value==null?'':Math.round(p.value*100)+'%';}")
        render_filterable_table(
            table[["model_label", "year_label", "n", "median_price", "p25", "p75",
                   "sold_median_price", "sold_n", "active_ads", "median_days_to_sell",
                   "mds", "pct_price_cut", "avg_days_since_cut"]],
            column_config={
                "model_label": dict(header_name="Model"),
                "year_label": dict(header_name="Year"),
                "n": dict(header_name="N", type=["numericColumn"], filter="agNumberColumnFilter"),
                "median_price": dict(header_name="Asking median", type=["numericColumn"],
                                      filter="agNumberColumnFilter", valueFormatter=euro_fmt),
                "p25": dict(header_name="P25", type=["numericColumn"],
                            filter="agNumberColumnFilter", valueFormatter=euro_fmt),
                "p75": dict(header_name="P75", type=["numericColumn"],
                            filter="agNumberColumnFilter", valueFormatter=euro_fmt),
                "sold_median_price": dict(header_name="Sold median", type=["numericColumn"],
                                           filter="agNumberColumnFilter", valueFormatter=euro_fmt),
                "sold_n": dict(header_name="N sold", type=["numericColumn"], filter="agNumberColumnFilter"),
                "active_ads": dict(header_name="Active", type=["numericColumn"], filter="agNumberColumnFilter"),
                "median_days_to_sell": dict(header_name="Days to sell", type=["numericColumn"],
                                             filter="agNumberColumnFilter", valueFormatter=days_fmt),
                "mds": dict(header_name="Days supply", type=["numericColumn"],
                            filter="agNumberColumnFilter", valueFormatter=days_fmt,
                            headerTooltip="Market Days Supply: days to clear current active listings "
                                          "at the last-60-day sell-through rate. Higher = oversupplied."),
                "pct_price_cut": dict(header_name="% cut", type=["numericColumn"],
                                       filter="agNumberColumnFilter", valueFormatter=pct_fmt,
                                       headerTooltip="Share of sampled ads for this model that have had "
                                                     "at least one price drop since first listed."),
                "avg_days_since_cut": dict(header_name="Last cut", type=["numericColumn"],
                                            filter="agNumberColumnFilter", valueFormatter=days_fmt,
                                            headerTooltip="Average days since the last price drop, for "
                                                           "ads that have had one."),
            },
            key="market_table",
        )
        st.caption("Days supply / % cut / Last cut come from the same 5,000-ad sample as the "
                   "regional/fuel breakdown below, so they're only populated for models with "
                   "enough sampled history — not every tracked model will show a value.")

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
                             lambda v: f"{v:.0f}d", color="linear-gradient(90deg,var(--warning-dark),var(--warning-main))",
                             count_fn=lambda r: f'{int(r["sold_n"])} sold')

        st.write("")
        st.markdown("**Most oversupplied models** (higher = more days to clear current stock — sourcing caution)")
        st.caption("Market Days Supply: active listings ÷ units sold in the last 60 days × 60. A model "
                   "sitting at 90+ days of supply is flooded — sourcing another one means competing "
                   "against a long queue of unsold comps, whatever the discount looks like on paper.")
        mds_chart = table.dropna(subset=["mds"])
        mds_chart = mds_chart[mds_chart["sold_n_60d"] >= 3].sort_values("mds", ascending=False).head(20).copy()
        if mds_chart.empty:
            st.caption("Not enough recent sales yet to estimate market days supply (need ≥3 sales in the last 60 days per model).")
        else:
            mds_chart["name"] = (mds_chart["brand"] + " " + mds_chart["model"] + " · "
                                 + mds_chart["year_bucket"].astype(int).astype(str) + "–"
                                 + (mds_chart["year_bucket"].astype(int) + 1).astype(str))
            render_bar_list(mds_chart.to_dict("records"), lambda r: r["name"], lambda r: r["mds"],
                             lambda v: f"{v:.0f}d", color="linear-gradient(90deg,var(--error-dark),var(--error-main))",
                             count_fn=lambda r: f'{int(r["sold_n_60d"])} sold/60d')

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
                             lambda r: r["median"], money, color="linear-gradient(90deg,var(--info-dark),var(--info-main))")

    st.write("")
    st.markdown("**Model deep-dive**")
    deep_opts = sorted(ads["brand"].dropna().unique()) if not ads.empty else []
    s1, s2, s3 = st.columns(3)
    sel_brand = s1.selectbox("Brand", deep_opts, key="market_deep_brand") if deep_opts else None
    pts = pd.DataFrame()
    sel_model = None
    sel_bucket = None
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
            st.scatter_chart(scatter_pts, x="mileage", y="price", color="#ff5000", x_label="km", y_label="€")
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
                st.line_chart(trend, x="week", y="price", color="#ff5000", x_label="week", y_label="€ (median)")

    st.write("")
    st.markdown("**Deal-rating distribution**")
    st.caption("How this selection's own listings are priced against their market median right now — "
               "same Great/Good/Fair/High/Overpriced classification the Deals tab uses per ad, counted "
               "up per model instead. A model stacked toward Great/Good has real flip supply; one stacked "
               "toward High/Overpriced is mostly sellers asking above market.")
    # Blacklist exclusion mirrors the `quality` slice used for the regional/fuel breakdown
    # above — without it a handful of scrap ("para peças"/"avariado") listings can silently
    # skew the median and manufacture a false rating.
    rating_pts = pts.dropna(subset=["price", "year", "brand", "model"]) if not pts.empty else pts
    if not rating_pts.empty:
        rating_pts = rating_pts[~rating_pts["is_blacklisted"].fillna(False)]
    ratings = pd.Series(dtype=object)
    stats_idx = {}
    if rating_pts.empty:
        st.caption("Pick a brand/model above to see its pricing distribution.")
    else:
        stats_idx = deal_engine.build_stats_index(stats.to_dict("records")) if not stats.empty else {}

        def _rating(row):
            stat = stats_idx.get(deal_engine.stats_key(row["brand"], row["model"], row["year"]))
            if not stat or not stat.get("median_price"):
                return None
            return deal_engine.deal_rating(1 - row["price"] / float(stat["median_price"]))

        ratings = rating_pts.apply(_rating, axis=1).dropna()
        if ratings.empty:
            st.caption("Not enough market-stats coverage for this selection yet (needs ≥5 comps in a bucket).")
        else:
            counts = ratings.value_counts().reindex(deal_engine.DEAL_RATING_ORDER).dropna()
            rows = [{"label": k, "value": int(v)} for k, v in counts.items()]
            render_bar_list(rows, lambda r: r["label"], lambda r: r["value"], lambda v: f"{v} ads",
                             color_fn=lambda r: RATING_COLORS[r["label"]])


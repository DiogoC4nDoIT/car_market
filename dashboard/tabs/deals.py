import streamlit as st

from dashboard.components import pagination_controls, render_deal_card
from dashboard.context import Context
from dashboard.data import apply_filters, clear_flag, create_saved_search
from dashboard.format_utils import CONF_META, money

DEALS_PAGE_SIZE = 20


def _clamp(pair, lo, hi):
    a, b = pair
    return max(lo, min(a, hi)), max(lo, min(b, hi))


def _restore_index(options, saved_value):
    return options.index(saved_value) if saved_value in options else 0


def render_deals_tab(ctx: Context):
    deals = ctx.deals
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

    with st.container(border=True):
        top = st.columns([8, 1])
        with top[1]:
            if st.button("Reset", icon=":material/refresh:", key="deals_reset_filters", use_container_width=True,
                         help="Clear all Deals filters"):
                st.session_state.deals_filters = {}
                for k in ("deals_filter_profit", "deals_filter_km", "deals_filter_year",
                          "deals_filter_brand", "deals_filter_model", "deals_filter_region",
                          "deals_filter_trust", "deals_filter_active"):
                    st.session_state.pop(k, None)
                st.rerun()
        f1, f2, f3 = st.columns(3)
        min_profit, max_profit = f1.slider(
            "PROFIT (€)", profit_lo, profit_hi,
            _clamp(saved.get("profit", (profit_default_lo, profit_hi)), profit_lo, profit_hi),
            step=10, key="deals_filter_profit",
        )
        min_km, max_km = f2.slider(
            "MILEAGE (KM)", km_lo, km_hi,
            _clamp(saved.get("km", (km_lo, km_hi)), km_lo, km_hi),
            step=1000, key="deals_filter_km",
        )
        min_year, max_year = f3.slider(
            "YEAR", year_lo, year_hi,
            _clamp(saved.get("year", (year_lo, year_hi)), year_lo, year_hi),
            key="deals_filter_year",
        )
        f4, f5, f6, f7, f8 = st.columns([1.3, 1.3, 1.1, 1, 1.1])
        brand_opts = ["All brands"] + sorted(deals["brand"].dropna().unique())
        brand = f4.selectbox("BRAND", brand_opts, index=_restore_index(brand_opts, saved.get("brand")),
                              key="deals_filter_brand")
        model_opts = ["All models"] + sorted(deals["model"].dropna().unique())
        model = f5.selectbox("MODEL", model_opts, index=_restore_index(model_opts, saved.get("model")),
                              key="deals_filter_model")
        region_opts = ["All regions"] + sorted(deals["region"].dropna().unique())
        region = f6.selectbox("REGION", region_opts, index=_restore_index(region_opts, saved.get("region")),
                               key="deals_filter_region")
        trust_opts = ["All levels", "alta", "media", "baixa"]
        conf = f7.selectbox("TRUST", trust_opts, index=_restore_index(trust_opts, saved.get("trust")),
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
    view = apply_filters(deals[~deals["ad_id"].isin(ctx.skipped_ids)], filters)

    with st.container(border=True, key="save_search_card"):
        st.markdown('<div class="stand-label" style="margin-bottom:10px">SAVE AS FAVOURITE DEAL</div>',
                    unsafe_allow_html=True)
        sn1, sn2 = st.columns([4, 1])
        search_name = sn1.text_input(
            "Search name", key="new_search_name", label_visibility="collapsed",
            placeholder="Name this filter combo, e.g. \"Cheap diesel wagons\"",
        )
        if sn2.button("Save search", icon=":material/save:", use_container_width=True):
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
            if ctx.skipped_ids:
                st.caption(f"{len(ctx.skipped_ids)} skipped")
                if st.button("Undo all", key="undo_all"):
                    for ad_id in ctx.skipped_ids:
                        clear_flag(ad_id, "skipped")
                    st.rerun()

    view = view.sort_values("score", ascending=False)
    total_pages = max(1, -(-len(view) // DEALS_PAGE_SIZE))

    st.write("")
    page = pagination_controls("deals_page", total_pages)
    start = (page - 1) * DEALS_PAGE_SIZE
    st.write("")
    if view.empty:
        st.caption("No deals match these filters — try widening the ranges above.")
    for _, d in view.iloc[start:start + DEALS_PAGE_SIZE].iterrows():
        render_deal_card(d, ctx.fav_ids, ctx.manual_fav_ids)

    st.write("")
    pagination_controls("deals_page", total_pages, widget_key="deals_page_bottom")

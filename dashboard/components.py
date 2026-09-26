"""Reusable Streamlit widgets shared across tabs: bar charts, the ag-Grid
table wrapper, pagination, small stat cards, and the deal card used on the
Deals/Favourites tabs."""
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder

from dashboard.data import set_flag, toggle_flag
from dashboard.format_utils import CONF_META, esc, fmt_date, money, sold_at, verdict_for


def render_bar_list(rows, label_fn, value_fn, fmt_fn,
                     color="linear-gradient(90deg,var(--success-dark),var(--success-main))", count_fn=None):
    max_val = max((value_fn(r) for r in rows), default=0)
    for r in rows:
        v = value_fn(r)
        pct = v / max_val * 100 if max_val else 0
        count_html = (
            f'<span style="width:56px;flex:none;text-align:right;font-size:11px;color:var(--text-disabled)">'
            f'{esc(count_fn(r))}</span>'
            if count_fn else ""
        )
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">'
            f'<span style="width:220px;flex:none;font-size:12px;color:var(--text-secondary);overflow:hidden;'
            f'text-overflow:ellipsis;white-space:nowrap">{esc(label_fn(r))}</span>'
            f'<div style="flex:1;height:16px;background:var(--grey-300);border-radius:var(--radius);overflow:hidden">'
            f'<div style="height:100%;background:{color};width:{pct:.0f}%"></div></div>'
            f'<span style="width:70px;flex:none;text-align:right;font:500 12px var(--font-family-monospace)">'
            f'{fmt_fn(v)}</span>{count_html}</div>',
            unsafe_allow_html=True,
        )


def render_filterable_table(df, column_config, key, height=700, paginate=False, page_size=200):
    """st.dataframe replacement with per-column header filters (ag-Grid)."""
    gb = GridOptionsBuilder.from_dataframe(df)
    # minWidth is the floor `flex` respects: on a wide container columns stretch to
    # fill it, but once the container (e.g. a phone screen) is narrower than the sum
    # of minWidths, ag-Grid switches to horizontal scroll instead of continuing to
    # shrink columns into unreadable slivers.
    gb.configure_default_column(filter=True, sortable=True,
                                 resizable=True, editable=False, flex=1, minWidth=110)
    for field, cfg in column_config.items():
        gb.configure_column(field, **cfg)
    if paginate:
        gb.configure_pagination(enabled=True, paginationAutoPageSize=False, paginationPageSize=page_size)
    # from_dataframe() bakes in autoSizeStrategy={"type": "fitGridWidth"}, which — like
    # the deprecated fit_columns_on_grid_load — only sizes columns once, at grid-ready
    # time, and sets fixed pixel widths that override `flex`. Disabling it here lets
    # `flex` keep columns proportionally sized on every later container resize, e.g.
    # when the sidebar nav is collapsed/expanded after the grid has already mounted.
    gb.configure_grid_options(autoSizeStrategy=None)
    AgGrid(df, gridOptions=gb.build(), height=height, theme="streamlit",
           key=key, allow_unsafe_jscode=True)


def pagination_controls(key, total_pages, widget_key=None):
    widget_key = widget_key or key
    st.session_state.setdefault(key, 1)
    page = min(max(st.session_state[key], 1), total_pages)
    st.session_state[key] = page
    c1, c2, c3 = st.columns([1, 3, 1])
    with c1:
        if st.button("Prev", icon=":material/chevron_left:", key=f"{widget_key}_prev",
                     disabled=page <= 1, use_container_width=True):
            st.session_state[key] = page - 1
            st.rerun()
    with c2:
        st.markdown(
            f'<div style="text-align:center;padding-top:8px;font-size:12px;color:var(--text-secondary)">'
            f'Page {page} of {total_pages}</div>',
            unsafe_allow_html=True,
        )
    with c3:
        if st.button("Next", icon=":material/chevron_right:", key=f"{widget_key}_next",
                     disabled=page >= total_pages, use_container_width=True):
            st.session_state[key] = page + 1
            st.rerun()
    return page


def kv_row(label, value_html):
    """One label/value line inside a .stand-card, e.g. 'Market median  €12,300'."""
    return f'<div class="stand-card-row"><span>{label}</span><span class="stand-mono">{value_html}</span></div>'


def stat_card(label, value_html, sub_html="", extra_top=""):
    """Small boxed stat used on the deal detail page (TRUST / LIQUIDITY / LISTED)."""
    return (
        f'<div class="stand-card"><div class="stand-label">{label}</div>'
        f'{extra_top}'
        f'<div style="font:500 15px var(--font-family);color:var(--text-primary);margin-top:7px">{value_html}</div>'
        f'<div style="font-size:11px;color:var(--text-secondary);margin-top:3px">{sub_html}</div></div>'
    )


def render_deal_card(d, fav_ids, manual_fav_ids=None, key_prefix=""):
    verdict, vbg, vcolor = verdict_for(d["display_score"])
    conf_label, conf_color = CONF_META.get(d["confidence"], ("—", "var(--text-disabled)"))
    with st.container(border=True):
        c0, c1, c2, c3, c4, c5 = st.columns([1.5, 2.7, 2, 1.6, 1, 1.3])
        with c0:
            # Photo links out to the live OLX ad — "Open" (c5) goes to the internal
            # detail page instead, so the two links are intentionally different targets.
            photo_inner = (
                f'<a href="{esc(d["url"])}" target="_blank">'
                f'<img class="stand-photo-img" src="{esc(d["photo_url"])}"></a>'
                if pd.notna(d.get("photo_url")) else
                f'<div class="stand-photo"><a href="{esc(d["url"])}" target="_blank">NO PHOTO</a></div>'
            )
            badge_html = (
                '<span class="stand-badge stand-photo-badge" '
                'style="background:var(--error-tint);color:var(--error-dark)">GONE</span>'
                if d.get("status") == "desaparecido" else ""
            )
            st.markdown(f'<div class="stand-photo-wrap">{photo_inner}{badge_html}</div>', unsafe_allow_html=True)
        with c1:
            year = int(d["year"]) if pd.notna(d.get("year")) else "?"
            km = f"{int(d['mileage']):,}" if pd.notna(d.get("mileage")) else "?"
            fuel = d["fuel"] if pd.notna(d.get("fuel")) else "?"
            region = d["region"] if pd.notna(d.get("region")) else "?"
            gone_dates_html = ""
            if d.get("status") == "desaparecido":
                gone_dates_html = (
                    f'<div class="stand-meta" style="margin-top:2px;color:var(--text-disabled)">'
                    f'published {fmt_date(d.get("olx_created_at"))} · sold {fmt_date(sold_at(d))}</div>'
                )
            st.markdown(
                f'<div class="stand-row-title"><a href="{esc(d["url"])}" target="_blank">{esc(d["title"])}</a></div>'
                f'<div class="stand-meta">{year} · {km} km · {esc(fuel)} · {esc(region)}</div>'
                f'{gone_dates_html}',
                unsafe_allow_html=True,
            )
        with c2:
            bar_pct = min(100, d["price"] / d["median_price"] * 100) if d["median_price"] else 0
            st.markdown(
                f'<div style="display:flex;align-items:baseline;gap:6px">'
                f'<span class="stand-mono" style="font-weight:600">{money(d["price"])}</span>'
                f'<span style="font-size:10.5px;color:var(--text-disabled)">/{money(d["median_price"])} mkt</span></div>'
                f'<div class="stand-bar-bg"><div class="stand-bar-fill" style="width:{bar_pct:.0f}%"></div></div>'
                f'<div class="stand-mono" style="font-size:11px;color:var(--success-dark);margin-top:5px">'
                f'{d["discount"] * 100:.0f}% below median</div>',
                unsafe_allow_html=True,
            )
        with c3:
            sell = d.get("median_days_to_sell")
            sell_text = f"~{int(sell)}d to sell" if pd.notna(sell) else "—"
            drop = d.get("price_drop")
            drop_html = (f'<span style="color:var(--error-dark);font-weight:500"> · ↓{money(drop)}</span>'
                         if pd.notna(drop) else "")
            days = int(d["days_listed"]) if pd.notna(d.get("days_listed")) else 0
            n = int(d["n"]) if pd.notna(d.get("n")) else 0
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:6px">'
                f'<span style="width:8px;height:8px;border-radius:50%;background:{conf_color};'
                f'display:inline-block"></span><span style="font-size:12px">{conf_label} trust · {n} comps</span></div>'
                f'<div style="font-size:12px;color:var(--text-secondary);margin-top:6px">{sell_text} · {days}d listed{drop_html}</div>',
                unsafe_allow_html=True,
            )
        with c4:
            st.markdown(
                f'<span class="stand-badge" style="background:{vbg};color:{vcolor}">{verdict.upper()}</span>'
                f'<div style="font:600 17px var(--font-family);color:var(--success-dark);margin-top:6px">'
                f'+{money(d["est_profit"])}</div>'
                f'<div class="stand-label">est. margin</div>',
                unsafe_allow_html=True,
            )
        with c5:
            ad_id = int(d["ad_id"])
            is_fav = ad_id in fav_ids
            # is_manual (not just is_fav) drives the toggle: an ad the crawler
            # auto-favourited via a saved-search match is already "starred" for
            # display, but clicking Fav on it should *upgrade* it to a manual
            # favourite (set_flag, which always writes source='manual'), not
            # delete the tracking — only a genuinely manual favourite gets
            # removed on click. Otherwise clicking Fav on an auto-tracked ad
            # (star already lit) silently un-favourited it entirely.
            manual_ids = manual_fav_ids if manual_fav_ids is not None else fav_ids
            is_manual = ad_id in manual_ids
            if st.button("Open", icon=":material/visibility:", key=f"{key_prefix}open_{ad_id}",
                         use_container_width=True):
                st.session_state.open_id = ad_id
                # Mirrored into the URL so a browser refresh (app.py reads this back into
                # open_id on load) keeps you on the detail page instead of dropping you
                # back to Deals with no sign anything you did in the meantime took effect.
                st.query_params["ad"] = str(ad_id)
                st.rerun()
            fav_icon = ":material/star:" if is_fav else ":material/star_border:"
            if st.button("Fav", icon=fav_icon, key=f"{key_prefix}fav_{ad_id}", use_container_width=True):
                toggle_flag(ad_id, "favourite", is_manual)
                st.rerun()
            if st.button("Skip", icon=":material/close:", key=f"{key_prefix}skip_{ad_id}", use_container_width=True):
                set_flag(ad_id, "skipped")
                st.rerun()

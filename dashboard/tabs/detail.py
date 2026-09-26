import pandas as pd
import streamlit as st

from src import config, deal_engine
from dashboard.components import kv_row, stat_card
from dashboard.context import Context
from dashboard.data import load_comps, set_flag, toggle_flag
from dashboard.format_utils import CONF_META, comp_sold_info, esc, money, score_color, verdict_for


def render_detail(ctx: Context, ad_id: int):
    row = ctx.deals[ctx.deals["ad_id"] == ad_id]
    if row.empty:
        st.session_state.open_id = None
        st.query_params.pop("ad", None)
        st.rerun()
        return
    d = row.iloc[0]

    if st.button("← Back to deals"):
        st.session_state.open_id = None
        st.query_params.pop("ad", None)
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
        + ('<span style="font-size:11px;color:var(--error-dark)">vanished — may be sold</span>' if gone else '') +
        f'</div><h1 style="font:100 27px var(--font-family);color:var(--text-primary);margin:12px 0 5px">'
        f'<a href="{esc(d["url"])}" target="_blank" style="color:inherit;text-decoration:none">{esc(d["title"])}</a></h1>'
        f'<div style="font-size:13px;color:var(--text-secondary)">{year} · {km} km · {esc(d.get("fuel") or "?")} · '
        f'{esc(d.get("region") or "?")}</div></div>'
        f'<div style="text-align:center;flex:none">'
        f'<div style="font:600 40px var(--font-family);color:{score_color(d["display_score"])};line-height:.9">'
        f'{d["display_score"]:.0f}</div>'
        f'<div class="stand-label" style="margin-top:2px">DEAL SCORE</div></div></div>',
        unsafe_allow_html=True,
    )

    if pd.notna(d.get("photo_url")):
        st.markdown(
            f'<a href="{esc(d["url"])}" target="_blank">'
            f'<img src="{esc(d["photo_url"])}" style="width:100%;border-radius:var(--radius);'
            f'margin-top:12px;object-fit:cover"></a>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<a href="{esc(d["url"])}" target="_blank" style="display:flex;width:100%;height:160px;'
            'border-radius:var(--radius);margin:18px 0;'
            'background:repeating-linear-gradient(135deg,var(--grey-100) 0 11px,var(--grey-200) 11px 22px);'
            'align-items:center;justify-content:center;font:400 10px var(--font-family-monospace);'
            f'color:var(--text-disabled)">VEHICLE PHOTO</a>',
            unsafe_allow_html=True,
        )

    resale_value = d["median_price"] * config.RESALE_FACTOR
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            '<div class="stand-card">'
            '<div class="stand-label" style="margin-bottom:11px">THE FLIP MATH</div>'
            + kv_row("Market median", money(d["median_price"]))
            + kv_row(f"Resale @ {int(config.RESALE_FACTOR * 100)}%", money(resale_value))
            + kv_row("Ask price", f"− {money(d['price'])}")
            + '<div style="height:1px;background:var(--divider);margin:8px 0"></div>'
            + '<div style="display:flex;justify-content:space-between;align-items:baseline">'
            + '<span style="font-size:13px;font-weight:500;color:var(--text-primary)">Est. profit</span>'
            + f'<span style="font:600 22px var(--font-family);color:var(--success-dark)">{money(d["est_profit"])}</span></div>'
            + '</div>',
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
            'background:linear-gradient(90deg,var(--success-main),var(--warning-main),var(--error-main));margin:16px 4px 8px">'
            f'<div style="position:absolute;top:-14px;transform:translateX(-50%);left:{pos(d["median_price"]):.0f}%;'
            f'font:400 9px var(--font-family-monospace);color:var(--text-secondary)">mkt</div>'
            f'<div style="position:absolute;top:-3px;width:2px;height:14px;background:var(--text-secondary);'
            f'left:{pos(d["median_price"]):.0f}%"></div>'
            f'<div style="position:absolute;top:-4px;transform:translateX(-50%);left:{pos(d["price"]):.0f}%;'
            'width:15px;height:15px;border-radius:50%;background:var(--primary-main);border:2.5px solid var(--bg-default);'
            'box-shadow:0 1px 4px rgba(0,0,0,.25)"></div></div>'
            f'<div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text-disabled);padding:0 2px">'
            f'<span>{money(p25)}</span><span>{money(p75)}</span></div>'
            f'<div style="font-size:12px;line-height:1.5;color:var(--text-secondary);margin-top:12px">This ask sits '
            f'<b style="color:var(--warning-dark)">{d["discount"] * 100:.0f}% below</b> market median across '
            f'{int(d["n"]) if pd.notna(d.get("n")) else 0} comparable listings.</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    t1, t2, t3 = st.columns(3)
    conf_label, conf_color = CONF_META.get(d.get("confidence"), ("—", "var(--text-disabled)"))
    trust_value = (
        f'<div style="display:flex;align-items:center;gap:7px">'
        f'<span style="width:9px;height:9px;border-radius:50%;background:{conf_color}"></span>'
        f'<span>{conf_label}</span></div>'
    )
    t1.markdown(
        stat_card("TRUST", trust_value,
                  f'{int(d["n"]) if pd.notna(d.get("n")) else 0} comparable ads'),
        unsafe_allow_html=True,
    )
    sell = d.get("median_days_to_sell")
    t2.markdown(
        stat_card("LIQUIDITY", f"~{int(sell)} days" if pd.notna(sell) else "—", "median time to sell"),
        unsafe_allow_html=True,
    )
    drop = d.get("price_drop")
    days = int(d["days_listed"]) if pd.notna(d.get("days_listed")) else 0
    listed_note = (f'<span style="color:var(--error-dark)">↓{money(drop)} recently</span>'
                   if pd.notna(drop) else "price steady")
    t3.markdown(
        stat_card("LISTED", f"{days} days", listed_note),
        unsafe_allow_html=True,
    )

    st.write("")
    b1, b2, b3 = st.columns([2, 1, 1])
    is_fav = ad_id in ctx.fav_ids
    is_manual = ad_id in ctx.manual_fav_ids
    with b1:
        st.link_button("Open on OLX", d["url"], icon=":material/open_in_new:", use_container_width=True)
    with b2:
        fav_icon = ":material/star:" if is_fav else ":material/star_border:"
        if st.button("Favourited" if is_fav else "Favourite", icon=fav_icon, key=f"fav_detail_{ad_id}",
                      use_container_width=True):
            # is_manual (not is_fav) drives the toggle so clicking Fav on an
            # ad auto-tracked via a saved-search match upgrades it to a
            # manual favourite instead of deleting the tracking — see the
            # matching comment in components.py's render_deal_card.
            toggle_flag(ad_id, "favourite", is_manual)
            st.rerun()
    with b3:
        if st.button("Skip", icon=":material/close:", key=f"skip_detail_{ad_id}", use_container_width=True):
            set_flag(ad_id, "skipped")
            st.session_state.open_id = None
            st.query_params.pop("ad", None)
            st.rerun()

    st.write("")
    st.markdown("**Similar Ads**")
    bucket = int(d["year_bucket"])
    fuel, mileage = d.get("fuel"), d.get("mileage")
    has_fuel = pd.notna(fuel)
    mileage_lo = mileage_hi = None
    if has_fuel and pd.notna(mileage):
        # Mirrors evaluate()'s preference order (src/deal_engine.py) — if a fine
        # (fuel + mileage-band) match exists, that's the basis the stored median/n
        # used, so mileage-banded comps should match it too. Fuel itself is always
        # enforced below regardless of this match — different fuel types have
        # structurally different prices and are never "comparable".
        key = deal_engine.fine_key(d["brand"], d["model"], bucket, fuel, mileage)
        match = ctx.fine_stats[
            (ctx.fine_stats["brand"].str.lower() == key[0]) & (ctx.fine_stats["model"].str.lower() == key[1])
            & (ctx.fine_stats["year_bucket"] == key[2]) & (ctx.fine_stats["fuel"].str.lower() == key[3])
            & (ctx.fine_stats["km_band"] == key[4])
        ]
        if not match.empty:
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
                delta_color = "var(--success-dark)" if delta >= 0 else "var(--error-dark)"
                delta_text = f"+{money(delta)}" if delta >= 0 else f"−{money(-delta)}"
                delta_html = f'<span style="font:500 12px var(--font-family-monospace);color:{delta_color}">{delta_text}</span>'
            self_html = ('<span class="stand-badge" style="background:var(--primary-tint);color:var(--primary-dark)">THIS AD</span>'
                         if is_self else "")
            sold, days_to_sell = comp_sold_info(cm.get("last_seen"), cm.get("olx_created_at"),
                                                 cm.get("url_status"), config.ACTIVE_WINDOW_DAYS)
            sold_text = f"SOLD · ~{int(days_to_sell)}d" if sold and days_to_sell is not None else "SOLD"
            sold_html = (f'<span class="stand-badge" style="background:var(--error-tint);color:var(--error-dark)">{sold_text}</span>'
                         if sold else "")
            row_bg = "var(--primary-tint)" if is_self else "var(--bg-paper)"
            row_border = "var(--primary-light)" if is_self else "var(--divider)"
            rank_color = "var(--primary-dark)" if is_self else "var(--text-disabled)"
            fuel_bit = f' · {esc(cm["fuel"])}' if pd.notna(cm.get("fuel")) else ""
            km_val = f'{int(cm["mileage"]):,}' if pd.notna(cm.get("mileage")) else "?"
            year_val = int(cm["year"]) if pd.notna(cm.get("year")) else "?"
            st.markdown(
                f'<a href="{esc(cm["url"])}" target="_blank" style="display:flex;align-items:center;gap:12px;'
                f'flex-wrap:wrap;padding:11px 14px;border-radius:var(--radius);background:{row_bg};'
                f'border:1px solid {row_border};text-decoration:none;color:inherit">'
                f'<span style="font:600 10px var(--font-family-monospace);color:{rank_color};width:20px">'
                f'#{int(cm["rank"])}</span>'
                f'<span style="font:600 14px var(--font-family-monospace);color:var(--text-primary);width:80px">'
                f'{money(cm["price"])}</span>'
                f'<span style="font-size:12px;color:var(--text-secondary)">{km_val} km · {year_val} · '
                f'{esc(cm.get("region") or "?")}{fuel_bit}</span>'
                f'<span style="flex:1"></span>{sold_html}{self_html}{delta_html}'
                f'<span style="font-size:11px;color:var(--primary-main);text-decoration:underline">View ad ↗</span>'
                f'</a>',
                unsafe_allow_html=True,
            )

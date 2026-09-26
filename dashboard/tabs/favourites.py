import pandas as pd
import streamlit as st

from dashboard.components import render_deal_card
from dashboard.context import Context
from dashboard.data import apply_filters, delete_saved_search
from dashboard.format_utils import describe_filters, sold_at


def _sorted_fav_view(ctx: Context, ad_ids: set, fav_added_at: pd.Series) -> pd.DataFrame:
    """Not-gone ads first (most recently favourited first), then gone ads
    (most recently sold first) — favouriting a live ad is "watch this", a
    gone one is "what happened to this"."""
    view = ctx.deals[ctx.deals["ad_id"].isin(ad_ids) & ~ctx.deals["ad_id"].isin(ctx.skipped_ids)].copy()
    view["fav_added_at"] = view["ad_id"].map(fav_added_at)
    view["sold_at"] = view.apply(sold_at, axis=1)
    is_gone = view["status"] == "desaparecido"
    return pd.concat([
        view[~is_gone].sort_values("fav_added_at", ascending=False),
        view[is_gone].sort_values("sold_at", ascending=False),
    ])


PAGE_SIZE = 10


def _render_with_show_more(view: pd.DataFrame, count_key: str, key_prefix: str, ctx: Context):
    st.session_state.setdefault(count_key, PAGE_SIZE)
    shown = st.session_state[count_key]
    for _, d in view.iloc[:shown].iterrows():
        render_deal_card(d, ctx.fav_ids, ctx.manual_fav_ids, key_prefix=key_prefix)
    if shown < len(view):
        if st.button(f"Show more ({len(view) - shown} left)", key=f"{key_prefix}show_more"):
            st.session_state[count_key] += PAGE_SIZE
            st.rerun()


def render_favourites_tab(ctx: Context):
    if not ctx.fav_ids and ctx.searches.empty:
        st.info("No favourites yet — tap Fav on a deal to save it, or save a filter combo "
                 "from the Deals tab as a favourite deal.")
        return

    fav_flags = ctx.flags[ctx.flags["flag"] == "favourite"] if not ctx.flags.empty else ctx.flags
    fav_added_at = fav_flags.set_index("ad_id")["created_at"] if not fav_flags.empty else pd.Series(dtype="object")
    manual_ids = ctx.manual_fav_ids
    auto_ids = ctx.fav_ids - manual_ids

    st.markdown("**Favourite ads**")
    st.caption("Ads you individually starred.")
    if not manual_ids:
        st.caption("No starred ads yet — tap Fav on a deal card to pin it here.")
    else:
        view = _sorted_fav_view(ctx, manual_ids, fav_added_at)
        st.caption(f"{len(view)} favourited")
        if view.empty:
            st.caption("All favourited ads are currently skipped.")
        _render_with_show_more(view, "favad_show_count", "favad_", ctx)

    st.write("")
    st.markdown("**Auto-tracked (saved search matches)**")
    st.caption("Not individually starred — the crawler tracks these automatically because "
               "they matched one of your favourite deal searches below, so price-drop "
               "alerts keep following them. Tap Fav to claim one as your own favourite.")
    if not auto_ids:
        st.caption("Nothing auto-tracked right now.")
    else:
        view = _sorted_fav_view(ctx, auto_ids, fav_added_at)
        show_gone = st.toggle("Show gone cars", value=False, key="favauto_show_gone")
        if not show_gone:
            view = view[view["status"] != "desaparecido"]
        st.caption(f"{len(view)} auto-tracked")
        if view.empty:
            st.caption("Nothing to show — all auto-tracked ads are currently skipped or gone.")
        _render_with_show_more(view, "favauto_show_count", "favauto_", ctx)

    st.write("")
    st.markdown("**Favourite deals**")
    st.caption("Saved filter combos from the Deals tab. New matches and price changes on "
               "favourite ads are also sent to Telegram.")
    if ctx.searches.empty:
        st.caption("No favourite deals saved yet — set filters on the Deals tab and use "
                   "\"Save as favourite deal\".")
        return

    for _, search in ctx.searches.sort_values("created_at").iterrows():
        search_id, name, filters = int(search["id"]), search["name"], search["filters"]
        view = apply_filters(ctx.deals[~ctx.deals["ad_id"].isin(ctx.skipped_ids)], filters)
        view = view.sort_values("score", ascending=False)
        label = f"{name} — {len(view)} matching deal{'s' if len(view) != 1 else ''}"
        with st.expander(label, expanded=False):
            if st.button("Delete", icon=":material/delete:", key=f"del_search_{search_id}"):
                delete_saved_search(search_id)
                st.rerun()

            st.caption(describe_filters(filters))
            st.write("")
            if view.empty:
                st.caption("No live deals match this search right now.")
            else:
                for _, d in view.iterrows():
                    render_deal_card(d, ctx.fav_ids, ctx.manual_fav_ids, key_prefix=f"search{search_id}_")

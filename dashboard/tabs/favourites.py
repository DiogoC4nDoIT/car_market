import streamlit as st

from dashboard.components import render_deal_card
from dashboard.context import Context
from dashboard.data import apply_filters, delete_saved_search
from dashboard.format_utils import describe_filters


def render_favourites_tab(ctx: Context):
    if not ctx.fav_ids and ctx.searches.empty:
        st.info("No favourites yet — tap ☆ Fav on a deal to save it, or save a filter combo "
                 "from the Deals tab as a favourite deal.")
        return

    st.markdown("**★ Favourite ads**")
    if not ctx.fav_ids:
        st.caption("No starred ads yet — tap ☆ Fav on a deal card to pin it here.")
    else:
        view = ctx.deals[ctx.deals["ad_id"].isin(ctx.fav_ids)].sort_values("score", ascending=False)
        st.caption(f"{len(view)} favourited")
        for _, d in view.iterrows():
            render_deal_card(d, ctx.fav_ids, key_prefix="favad_")

    st.write("")
    st.markdown("**⭐ Favourite deals**")
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
        label = f"⭐ {name} — {len(view)} matching deal{'s' if len(view) != 1 else ''}"
        with st.expander(label, expanded=False):
            if st.button("🗑 Delete", key=f"del_search_{search_id}"):
                delete_saved_search(search_id)
                st.rerun()

            st.caption(describe_filters(filters))
            st.write("")
            if view.empty:
                st.caption("No live deals match this search right now.")
            else:
                for _, d in view.iterrows():
                    render_deal_card(d, ctx.fav_ids, key_prefix=f"search{search_id}_")

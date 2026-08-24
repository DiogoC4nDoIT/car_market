import streamlit as st
from st_aggrid.shared import JsCode

from dashboard.components import render_filterable_table
from dashboard.data import load_all_ads

_TITLE_LINK_RENDERER = JsCode("""
    class TitleLinkRenderer {
        init(params) {
            this.eGui = document.createElement('span');
            this.eGui.style.display = 'inline-flex';
            this.eGui.style.alignItems = 'center';
            this.eGui.style.gap = '6px';
            const text = document.createElement('span');
            text.innerText = params.value || '';
            this.eGui.appendChild(text);
            if (params.data && params.data.url) {
                const a = document.createElement('a');
                a.href = params.data.url;
                a.target = '_blank';
                a.title = 'Open ad on OLX';
                a.innerText = '\\u{1F517}';
                a.style.textDecoration = 'none';
                a.style.flexShrink = '0';
                this.eGui.appendChild(a);
            }
        }
        getGui() { return this.eGui; }
    }
""")


def render_ads_tab():
    all_ads = load_all_ads()
    if all_ads.empty:
        st.info("No ads tracked yet.")
        return

    render_filterable_table(
        all_ads[["title", "price", "brand", "model", "year", "mileage", "region", "url", "first_seen"]],
        column_config={
            "title": dict(cellRenderer=_TITLE_LINK_RENDERER, minWidth=260),
            "price": dict(type=["numericColumn"], filter="agNumberColumnFilter"),
            "year": dict(type=["numericColumn"], filter="agNumberColumnFilter"),
            "mileage": dict(type=["numericColumn"], filter="agNumberColumnFilter"),
            "url": dict(hide=True, filter=False),
        },
        key="ads_table",
        paginate=True,
    )

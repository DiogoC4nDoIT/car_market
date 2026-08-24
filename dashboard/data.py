"""All Supabase access and st.cache_data-backed queries/mutations. Keeping
this in one place means every read/write against the DB is easy to find, and
tab modules never need to know about table names or PostgREST pagination."""
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from supabase import create_client

from src import deal_engine


def secret(name):
    try:
        value = st.secrets.get(name)
    except st.errors.StreamlitSecretNotFoundError:
        value = None
    return value or os.getenv(name)


@st.cache_resource
def sb():
    return create_client(secret("SUPABASE_URL"), secret("SUPABASE_KEY"))


def _fetch_paged(q, limit=None):
    """PostgREST caps a single request at its configured max-rows (commonly 1000)
    regardless of the .limit() we pass, so page via .range() until `limit` is hit
    or the result set is exhausted — otherwise `limit=5000` silently truncates
    to ~1000. `limit=None` pages until the result set is exhausted (fetch everything)."""
    rows, offset = [], 0
    while limit is None or offset < limit:
        chunk = 1000 if limit is None else min(1000, limit - offset)
        page = q.range(offset, offset + chunk - 1).execute().data
        rows.extend(page)
        if len(page) < chunk:
            break
        offset += chunk
    return pd.DataFrame(rows)


@st.cache_data(ttl=120)
def load(table, order=None, limit=2000):
    q = sb().table(table).select("*")
    if order:
        q = q.order(order, desc=True)
    return _fetch_paged(q, limit)


@st.cache_data(ttl=120)
def count_rows(table):
    return sb().table(table).select("id", count="exact").limit(1).execute().count


@st.cache_data(ttl=120)
def count_ads(brand=None, region=None, fuel=None, yr_lo=None, yr_hi=None,
              p_lo=None, p_hi=None, min_last_seen=None, min_first_seen=None):
    """Exact server-side count matching the Market tab filters — the `ads` df loaded via
    `load()` is capped (currently 5000 of 13k+ rows) for the charts/deep-dive below, so KPI
    cards must count against the real table instead or they'd plateau at the cap."""
    q = sb().table("ads").select("id", count="exact")
    if brand and brand != "All brands":
        q = q.eq("brand", brand)
    if region and region != "All regions":
        q = q.eq("region", region)
    if fuel and fuel != "All fuels":
        q = q.eq("fuel", fuel)
    if yr_lo is not None:
        q = q.gte("year", yr_lo).lte("year", yr_hi)
    if p_lo is not None:
        q = q.gte("price", p_lo).lte("price", p_hi)
    if min_last_seen is not None:
        q = q.gte("last_seen", min_last_seen)
    if min_first_seen is not None:
        q = q.gte("first_seen", min_first_seen)
    return q.limit(1).execute().count


def set_flag(ad_id: int, flag: str):
    sb().table("ad_flags").upsert({"ad_id": int(ad_id), "flag": flag}).execute()
    st.cache_data.clear()


def clear_flag(ad_id: int, flag: str):
    sb().table("ad_flags").delete().eq("ad_id", int(ad_id)).eq("flag", flag).execute()
    st.cache_data.clear()


def toggle_flag(ad_id: int, flag: str, currently_set: bool):
    (clear_flag if currently_set else set_flag)(ad_id, flag)


def create_saved_search(name: str, filters: dict):
    sb().table("saved_searches").insert({"name": name, "filters": filters}).execute()
    st.cache_data.clear()


def delete_saved_search(search_id: int):
    sb().table("saved_searches").delete().eq("id", int(search_id)).execute()
    st.cache_data.clear()


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """Applies a saved-search filter dict to a deals-shaped dataframe using the same
    predicate the crawler uses (deal_engine.matches_filters) before sending a "new
    favourite deal" Telegram alert, so the two can never disagree on what matches."""
    if df.empty:
        return df
    mask = df.apply(lambda r: deal_engine.matches_filters(r.to_dict(), filters), axis=1)
    return df[mask]


@st.cache_data(ttl=120)
def load_all_ads():
    return _fetch_paged(sb().table("ads").select("*").order("first_seen", desc=True))


@st.cache_data(ttl=120)
def load_comps(brand, model, year_lo, year_hi, fuel=None, mileage_lo=None, mileage_hi=None):
    """Fetch comps directly from Supabase (uncapped), unlike the 5000-row `ads` df. `fuel`
    is always enforced when known (different fuel types price differently); mileage band is
    only passed when it matches the fine basis deal_engine.evaluate() used for this deal's
    stored median (see deal_engine.fine_key())."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    q = (sb().table("ads").select("*")
         .eq("brand", brand).eq("model", model)
         .gte("year", year_lo).lte("year", year_hi)
         .eq("is_blacklisted", False).gt("price", 100).gte("last_seen", cutoff))
    if fuel is not None:
        q = q.eq("fuel", fuel)
    if mileage_lo is not None:
        q = q.gte("mileage", mileage_lo)
    if mileage_hi is not None:
        q = q.lt("mileage", mileage_hi)
    return _fetch_paged(q, 2000)


@st.cache_data(ttl=120)
def load_price_history(ad_ids: tuple):
    """price_history has no brand/model of its own, so trend lookups are keyed off
    a caller-supplied set of ad ids (usually from an already brand/model-filtered
    ads slice) and batched at 500 ids/request like db.py's known_prices()."""
    if not ad_ids:
        return pd.DataFrame()
    frames = []
    for i in range(0, len(ad_ids), 500):
        chunk = list(ad_ids[i:i + 500])
        res = sb().table("price_history").select("*").in_("ad_id", chunk).execute()
        frames.append(pd.DataFrame(res.data))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

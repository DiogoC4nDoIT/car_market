import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from supabase import create_client

from . import config

log = logging.getLogger(__name__)

_client = None


def client():
    global _client
    if _client is None:
        if not (config.SUPABASE_URL and config.SUPABASE_KEY):
            raise RuntimeError("SUPABASE_URL / SUPABASE_KEY not configured (see .env.example)")
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


def _chunks(seq: list, size: int = 500):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _pages(query, page_size: int = 1000):
    """Page a PostgREST query past the server's per-request row cap (db-max-rows,
    typically 1000, applied regardless of any client-side .limit()): keep asking
    for the next .range() until a short page signals the result set is done."""
    offset = 0
    while True:
        page = query.range(offset, offset + page_size - 1).execute().data
        if page:
            yield page
        if len(page) < page_size:
            return
        offset += page_size


def _warn_if_no_rows(res, what: str):
    """PostgREST answers 200 with empty data when RLS filters out an UPDATE's
    target rows (bit us before — see the RLS note in supabase_schema.sql), so a
    write that matched nothing needs to be loud."""
    if not res.data:
        log.warning("update matched no rows (%s) — RLS policy or bad filter?", what)


def known_prices(ids: list[int]) -> dict[int, float | None]:
    """Currently stored price per known ad id (missing id = never seen)."""
    out = {}
    for chunk in _chunks(ids):
        res = client().table("ads").select("id, price").in_("id", chunk).execute()
        out.update({r["id"]: r["price"] for r in res.data})
    return out


def upsert_ads(ads: list[dict]):
    now = datetime.now(timezone.utc).isoformat()
    rows = {a["id"]: {**{k: v for k, v in a.items() if not k.startswith("_")},
                      "last_seen": now}
            for a in ads}
    for chunk in _chunks(list(rows.values())):
        client().table("ads").upsert(chunk).execute()


def read_view(view: str) -> list[dict]:
    return [r for page in _pages(client().table(view).select("*")) for r in page]


def market_stats() -> list[dict]:
    return read_view("market_stats")


def market_stats_fine() -> list[dict]:
    return read_view("market_stats_fine")


def market_stats_fuel() -> list[dict]:
    return read_view("market_stats_fuel")


def insert_price_history(rows: list[dict]):
    for chunk in _chunks(rows):
        client().table("price_history").insert(chunk).execute()


def existing_deal_ids(ids: list[int]) -> set[int]:
    if not ids:
        return set()
    res = client().table("deals").select("ad_id").in_("ad_id", ids).execute()
    return {r["ad_id"] for r in res.data}


def recent_deal_fingerprints(days: int) -> set[str]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    res = (client().table("deals").select("fingerprint")
           .gte("created_at", since).not_.is_("fingerprint", "null").execute())
    return {r["fingerprint"] for r in res.data}


def insert_deals(deals: list[dict]):
    if deals:
        client().table("deals").upsert(deals, on_conflict="ad_id").execute()


def mark_notified(ad_id: int):
    res = client().table("deals").update({"notified": True}).eq("ad_id", ad_id).execute()
    _warn_if_no_rows(res, f"deals.notified ad_id={ad_id}")


def update_deal_pricing(rows: list[dict]):
    """Plain per-row UPDATE of recomputed pricing fields only — leaves
    notified/created_at/fingerprint untouched, unlike insert_deals()'s upsert.
    (Per-row because every row carries different values; only used by the
    one-off backfill script.)"""
    fields = ("median_price", "discount", "est_profit", "n", "confidence", "score")
    for r in rows:
        res = (client().table("deals")
               .update({f: r[f] for f in fields})
               .eq("ad_id", r["ad_id"]).execute())
        _warn_if_no_rows(res, f"deals pricing ad_id={r['ad_id']}")


def deal_ad_ids() -> list[int]:
    """Ad ids currently tracked as deals — what's actually shown on the dashboard,
    so url_checker rechecks these every run regardless of backlog ordering."""
    res = client().table("deals").select("ad_id").execute()
    return [r["ad_id"] for r in res.data]


def ads_to_check(limit: int, lookback_days: int, priority_ids: list[int] = ()) -> list[dict]:
    """Ads worth re-checking against their live OLX page: never checked, or last
    checked while still 'active' (skip 'sold'/'removed' — terminal, no need to
    recheck). priority_ids are always included (uncapped) on top of `limit`; the
    rest is bounded to recently-seen ads and ordered so stalest-checked go first,
    so nothing sits unchecked indefinitely once the backlog is caught up."""
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    seen: set[int] = set()
    out: list[dict] = []

    def add(rows):
        for r in rows:
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(r)

    for chunk in _chunks(list(priority_ids)):
        res = (client().table("ads").select("id, url")
               .in_("id", chunk)
               .or_("url_status.is.null,url_status.eq.active")
               .execute())
        add(res.data)

    backlog_target = len(out) + limit
    backlog = (client().table("ads").select("id, url")
               .or_("url_status.is.null,url_status.eq.active")
               .gte("first_seen", since)
               .order("url_checked_at", nullsfirst=True))
    if len(out) < backlog_target:
        for page in _pages(backlog):
            add(page)
            if len(out) >= backlog_target:
                break
    return out[:backlog_target]


def update_url_status(rows: list[dict]):
    """Plain UPDATEs, not upsert — these ids always already exist (they came from
    a SELECT on ads), and upsert's INSERT ON CONFLICT validates NOT NULL columns
    (like `url`, absent from this partial payload) on the insert attempt even when
    the row will only ever be updated. Rows are grouped by identical payload
    (status only takes a few values and each run shares one url_checked_at), so a
    full batch costs a handful of requests instead of one per row."""
    groups = defaultdict(list)
    for r in rows:
        groups[(r["url_status"], r["url_checked_at"])].append(r["id"])
    for (status, checked_at), ids in groups.items():
        for chunk in _chunks(ids):
            res = (client().table("ads")
                   .update({"url_status": status, "url_checked_at": checked_at})
                   .in_("id", chunk).execute())
            _warn_if_no_rows(res, f"ads.url_status={status} ({len(chunk)} ids)")


def favourite_ad_ids() -> set[int]:
    res = client().table("ad_flags").select("ad_id").eq("flag", "favourite").execute()
    return {r["ad_id"] for r in res.data}


def saved_searches() -> list[dict]:
    return client().table("saved_searches").select("*").order("created_at").execute().data


def create_saved_search(name: str, filters: dict):
    client().table("saved_searches").insert({"name": name, "filters": filters}).execute()


def delete_saved_search(search_id: int):
    client().table("saved_searches").delete().eq("id", search_id).execute()


def existing_search_match_ad_ids(search_id: int) -> set[int]:
    res = (client().table("saved_search_matches").select("ad_id")
           .eq("search_id", search_id).execute())
    return {r["ad_id"] for r in res.data}


def insert_search_matches(rows: list[dict]):
    for chunk in _chunks(rows):
        client().table("saved_search_matches").insert(chunk).execute()


def start_crawl_run(mode: str) -> int | None:
    res = client().table("crawl_runs").insert({"mode": mode}).execute()
    return res.data[0]["id"] if res.data else None


def finish_crawl_run(run_id: int | None, ads_fetched: int, deals_found: int):
    if run_id is None:
        return
    res = client().table("crawl_runs").update({
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "ads_fetched": ads_fetched,
        "deals_found": deals_found,
    }).eq("id", run_id).execute()
    _warn_if_no_rows(res, f"crawl_runs.finished_at id={run_id}")

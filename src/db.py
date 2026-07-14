from datetime import datetime, timedelta, timezone

from supabase import create_client

from . import config

_client = None


def client():
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


def known_prices(ids: list[int]) -> dict[int, float | None]:
    """Currently stored price per known ad id (missing id = never seen)."""
    out = {}
    for i in range(0, len(ids), 500):
        res = client().table("ads").select("id, price").in_("id", ids[i:i + 500]).execute()
        out.update({r["id"]: r["price"] for r in res.data})
    return out


def upsert_ads(ads: list[dict]):
    now = datetime.now(timezone.utc).isoformat()
    rows = {a["id"]: {**{k: v for k, v in a.items() if not k.startswith("_")},
                      "last_seen": now}
            for a in ads}
    rows = list(rows.values())
    for i in range(0, len(rows), 500):
        client().table("ads").upsert(rows[i:i + 500]).execute()


def read_view(view: str) -> list[dict]:
    out, page = [], 0
    while True:
        res = (client().table(view).select("*")
               .range(page * 1000, page * 1000 + 999).execute())
        out.extend(res.data)
        if len(res.data) < 1000:
            return out
        page += 1


def market_stats() -> list[dict]:
    return read_view("market_stats")


def market_stats_fine() -> list[dict]:
    return read_view("market_stats_fine")


def insert_price_history(rows: list[dict]):
    for i in range(0, len(rows), 500):
        client().table("price_history").insert(rows[i:i + 500]).execute()


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
    client().table("deals").update({"notified": True}).eq("ad_id", ad_id).execute()


def start_crawl_run(mode: str) -> int | None:
    res = client().table("crawl_runs").insert({"mode": mode}).execute()
    return res.data[0]["id"] if res.data else None


def finish_crawl_run(run_id: int | None, ads_fetched: int, deals_found: int):
    if run_id is None:
        return
    client().table("crawl_runs").update({
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "ads_fetched": ads_fetched,
        "deals_found": deals_found,
    }).eq("id", run_id).execute()

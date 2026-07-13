from supabase import create_client

from . import config

_client = None


def client():
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


def known_ids(ids: list[int]) -> set[int]:
    if not ids:
        return set()
    res = client().table("ads").select("id").in_("id", ids).execute()
    return {r["id"] for r in res.data}


def upsert_ads(ads: list[dict]):
    rows = {a["id"]: {k: v for k, v in a.items() if not k.startswith("_")} for a in ads}
    rows = list(rows.values())
    for i in range(0, len(rows), 500):
        client().table("ads").upsert(rows[i:i + 500]).execute()


def market_stats() -> list[dict]:
    out, page = [], 0
    while True:
        res = (client().table("market_stats").select("*")
               .range(page * 1000, page * 1000 + 999).execute())
        out.extend(res.data)
        if len(res.data) < 1000:
            return out
        page += 1


def existing_deal_ids(ids: list[int]) -> set[int]:
    if not ids:
        return set()
    res = client().table("deals").select("ad_id").in_("ad_id", ids).execute()
    return {r["ad_id"] for r in res.data}


def insert_deals(deals: list[dict]):
    if deals:
        client().table("deals").upsert(deals, on_conflict="ad_id").execute()


def mark_notified(ad_id: int):
    client().table("deals").update({"notified": True}).eq("ad_id", ad_id).execute()

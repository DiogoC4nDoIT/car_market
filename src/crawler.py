"""Main entry point. Run: python -m src.crawler"""
import logging

import requests

from . import config, db, deal_engine, notify, olx_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def resolve_category() -> int:
    cid = config.CATEGORY_ID
    try:
        if olx_api.fetch_page(cid, 0, price_to=config.MARKET_CEILING):
            return cid
    except requests.RequestException as e:
        log.warning("category_id %s probe failed (%s: %s)", cid, type(e).__name__, e)
    log.warning("category_id %s returned nothing; auto-discovering...", cid)
    discovered = olx_api.discover_category_id()
    if discovered:
        log.info("discovered category_id=%s", discovered)
        return discovered
    raise SystemExit("Could not resolve OLX Carros category id")


def fetch_incremental(cid: int) -> tuple[list[dict], dict]:
    """Newest first; stop once a whole page is already stored. Known ads are
    kept so their last_seen/price get refreshed on upsert. Also returns the
    stored prices already fetched per page, so run() needn't re-query them."""
    ads, prev_prices, page = [], {}, 0
    while page * olx_api.LIMIT < olx_api.MAX_OFFSET:
        batch = olx_api.fetch_page(cid, page * olx_api.LIMIT,
                                   price_to=config.MARKET_CEILING)
        if not batch:
            break
        ads.extend(batch)
        known = db.known_prices([a["id"] for a in batch])
        prev_prices.update(known)
        if all(a["id"] in known for a in batch):
            break
        page += 1
    return ads, prev_prices


def price_history_rows(ads: list[dict], prev: dict) -> list[dict]:
    """One row on first sighting, one per price change."""
    rows, seen = [], set()
    for a in ads:
        if a["id"] in seen or a.get("price") is None:
            continue
        seen.add(a["id"])
        old = prev.get(a["id"])
        if old is None or float(old) != float(a["price"]):
            rows.append({"ad_id": a["id"], "price": a["price"]})
    return rows


def run():
    run_id = db.start_crawl_run("deep_sweep" if config.DEEP_SWEEP else "incremental")
    cid = resolve_category()

    if config.DEEP_SWEEP:
        log.info("deep sweep (price-bucketed) up to %.0f EUR", config.MARKET_CEILING)
        ads = olx_api.fetch_deep_sweep(cid, config.MARKET_CEILING)
        prev_prices = None
    else:
        ads, prev_prices = fetch_incremental(cid)

    log.info("fetched %d ads", len(ads))
    if not ads:
        db.finish_crawl_run(run_id, 0, 0)
        return

    for a in ads:
        a["is_blacklisted"] = deal_engine.is_blacklisted(a)

    if prev_prices is None:
        prev_prices = db.known_prices([a["id"] for a in ads])
    db.upsert_ads(ads)
    history = price_history_rows(ads, prev_prices)
    log.info("price history rows: %d", len(history))
    db.insert_price_history(history)

    stats = deal_engine.build_stats_index(db.market_stats())
    fine = deal_engine.build_fine_index(db.market_stats_fine())
    fuel = deal_engine.build_fuel_index(db.market_stats_fuel())
    log.info("market stats groups: %d coarse, %d fuel, %d fine", len(stats), len(fuel), len(fine))

    candidates = [d for d in (deal_engine.evaluate(a, stats, fine, fuel) for a in ads) if d]
    already = db.existing_deal_ids([d["ad_id"] for d in candidates])
    relisted = db.recent_deal_fingerprints(config.RELIST_DEDUPE_DAYS)
    new_deals, seen_fps = [], set()
    for d in candidates:
        if d["ad_id"] in already:
            continue
        if d["fingerprint"] in relisted or d["fingerprint"] in seen_fps:
            log.info("skipping re-listed ad %s", d["ad_id"])
            continue
        seen_fps.add(d["fingerprint"])
        new_deals.append(d)
    log.info("new deals: %d", len(new_deals))
    db.insert_deals(new_deals)
    db.finish_crawl_run(run_id, len(ads), len(new_deals))

    ads_by_id = {a["id"]: a for a in ads}
    notify_favourite_price_changes(history, prev_prices, ads_by_id)
    notify_saved_search_matches(new_deals, ads_by_id)


def notify_favourite_price_changes(history: list[dict], prev_prices: dict, ads_by_id: dict):
    """`history` (from price_history_rows) has one row per genuine price change this
    run plus one per first sighting — only alert on the former, and only for ads the
    user has starred as favourite."""
    fav_ids = db.favourite_ad_ids()
    if not fav_ids:
        return
    for row in history:
        ad_id = row["ad_id"]
        old_price = prev_prices.get(ad_id)
        if old_price is None or ad_id not in fav_ids:
            continue
        ad = ads_by_id[ad_id]
        notify.send_telegram(
            notify.format_price_change(ad, float(old_price), float(row["price"])),
            ad.get("photo_url"),
        )


def _filter_row(ad: dict, deal: dict) -> dict:
    status = "desaparecido" if ad.get("url_status") in ("sold", "removed") else "ativo"
    return {
        "est_profit": deal["est_profit"], "mileage": ad.get("mileage"), "year": ad.get("year"),
        "brand": ad.get("brand"), "model": ad.get("model"), "region": ad.get("region"),
        "confidence": deal.get("confidence"), "status": status,
    }


def notify_saved_search_matches(new_deals: list[dict], ads_by_id: dict):
    """A saved search's filters are a refinement of the deal criteria already applied
    by deal_engine.evaluate(), so it can only start matching an ad the moment that ad
    becomes a deal — checking just this run's new_deals (not the whole deals table) is
    sufficient."""
    searches = db.saved_searches()
    if not searches or not new_deals:
        return
    for search in searches:
        matched = [d for d in new_deals
                   if deal_engine.matches_filters(_filter_row(ads_by_id[d["ad_id"]], d), search["filters"])]
        if not matched:
            continue
        already = db.existing_search_match_ad_ids(search["id"])
        new_rows = []
        for deal in matched:
            ad_id = deal["ad_id"]
            if ad_id in already:
                continue
            ad = ads_by_id[ad_id]
            notify.send_telegram(
                notify.format_new_match(ad, deal, search["name"]), ad.get("photo_url"),
            )
            # Matching a saved search makes an ad a favourite too, so price-drop
            # alerts (notify_favourite_price_changes) start tracking it going forward.
            db.set_favourite_from_search_match(ad_id)
            new_rows.append({"search_id": search["id"], "ad_id": ad_id})
        db.insert_search_matches(new_rows)


if __name__ == "__main__":
    run()

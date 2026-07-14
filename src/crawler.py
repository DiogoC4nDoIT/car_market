"""Main entry point. Run: python -m src.crawler"""
import logging

from . import config, db, deal_engine, notify, olx_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def resolve_category() -> int:
    cid = config.CATEGORY_ID
    try:
        if olx_api.fetch_page(cid, 0, price_to=config.MARKET_CEILING):
            return cid
    except Exception:
        pass
    log.warning("category_id %s returned nothing; auto-discovering...", cid)
    discovered = olx_api.discover_category_id()
    if discovered:
        log.info("discovered category_id=%s", discovered)
        return discovered
    raise SystemExit("Could not resolve OLX Carros category id")


def fetch_incremental(cid: int) -> list[dict]:
    """Newest first; stop once a whole page is already stored. Known ads are
    kept so their last_seen/price get refreshed on upsert."""
    ads, page = [], 0
    while page * olx_api.LIMIT < olx_api.MAX_OFFSET:
        batch = olx_api.fetch_page(cid, page * olx_api.LIMIT,
                                   price_to=config.MARKET_CEILING)
        if not batch:
            break
        ads.extend(batch)
        known = db.known_prices([a["id"] for a in batch])
        if all(a["id"] in known for a in batch):
            break
        page += 1
    return ads


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
    else:
        ads = fetch_incremental(cid)

    log.info("fetched %d ads", len(ads))
    if not ads:
        db.finish_crawl_run(run_id, 0, 0)
        return

    for a in ads:
        a["is_blacklisted"] = deal_engine.is_blacklisted(a)

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
    for deal in sorted(new_deals, key=lambda d: -d["score"]):
        ad = ads_by_id[deal["ad_id"]]
        if notify.send_telegram(notify.format_deal(deal, ad), ad.get("photo_url")):
            db.mark_notified(deal["ad_id"])


if __name__ == "__main__":
    run()

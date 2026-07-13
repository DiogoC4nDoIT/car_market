"""Main entry point. Run: python -m src.crawler"""
import logging

from . import config, db, deal_engine, notify, olx_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def resolve_category() -> int:
    cid = config.CATEGORY_ID
    try:
        if olx_api.fetch_page(cid, 0, price_to=config.PRICE_CEILING):
            return cid
    except Exception:
        pass
    log.warning("category_id %s returned nothing; auto-discovering...", cid)
    discovered = olx_api.discover_category_id()
    if discovered:
        log.info("discovered category_id=%s", discovered)
        return discovered
    raise SystemExit("Could not resolve OLX Carros category id")


def run():
    cid = resolve_category()

    if config.DEEP_SWEEP:
        log.info("deep sweep (price-bucketed) up to %.0f EUR", config.PRICE_CEILING)
        ads = olx_api.fetch_deep_sweep(cid, config.PRICE_CEILING)
    else:
        # incremental: newest first, stop once a whole page is already stored
        ads, page = [], 0
        while page * olx_api.LIMIT < olx_api.MAX_OFFSET:
            batch = olx_api.fetch_page(cid, page * olx_api.LIMIT,
                                       price_to=config.PRICE_CEILING)
            if not batch:
                break
            known = db.known_ids([a["id"] for a in batch])
            fresh = [a for a in batch if a["id"] not in known]
            ads.extend(fresh)
            if not fresh:
                break
            page += 1

    log.info("fetched %d new/updated ads", len(ads))
    if not ads:
        return

    for a in ads:
        a["is_blacklisted"] = deal_engine.is_blacklisted(a)
    db.upsert_ads(ads)

    stats = deal_engine.build_stats_index(db.market_stats())
    log.info("market stats groups: %d", len(stats))

    candidates = [d for d in (deal_engine.evaluate(a, stats) for a in ads) if d]
    already = db.existing_deal_ids([d["ad_id"] for d in candidates])
    new_deals = [d for d in candidates if d["ad_id"] not in already]
    log.info("new deals: %d", len(new_deals))
    db.insert_deals(new_deals)

    ads_by_id = {a["id"]: a for a in ads}
    for deal in sorted(new_deals, key=lambda d: -d["score"]):
        if notify.send_telegram(notify.format_deal(deal, ads_by_id[deal["ad_id"]])):
            db.mark_notified(deal["ad_id"])


if __name__ == "__main__":
    run()

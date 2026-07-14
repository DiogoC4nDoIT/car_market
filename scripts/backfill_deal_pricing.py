"""One-off backfill: recompute stored deals pricing (median/discount/profit/n/
confidence/score) with the fuel-aware market_stats_fuel tier (see deal_engine.pick_stat()).

Existing deals rows were scored once at crawl time and never recomputed, so ones
scored before this tier existed can still carry numbers derived from a fuel-blind
coarse bucket. This script corrects them in place without re-running the
accept/reject gating (budget/min-discount/min-profit) — no deals are removed,
only their displayed numbers are refreshed.

Run once: python -m scripts.backfill_deal_pricing
"""
import logging

from src import db, deal_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def fetch_deals_with_ads() -> list[dict]:
    rows, offset, page = [], 0, 1000
    while True:
        res = (db.client().table("deals")
               .select("ad_id, ads(brand, model, year, mileage, fuel, price, is_blacklisted)")
               .range(offset, offset + page - 1).execute())
        for r in res.data:
            ad = r.pop("ads") or {}
            ad["id"] = r["ad_id"]
            rows.append(ad)
        if len(res.data) < page:
            return rows
        offset += page


def main():
    ads = fetch_deals_with_ads()
    log.info("fetched %d existing deals", len(ads))

    stats = deal_engine.build_stats_index(db.market_stats())
    fine = deal_engine.build_fine_index(db.market_stats_fine())
    fuel = deal_engine.build_fuel_index(db.market_stats_fuel())
    log.info("market stats groups: %d coarse, %d fuel, %d fine", len(stats), len(fuel), len(fine))

    updates, skipped = [], 0
    for ad in ads:
        if not (ad.get("price") and ad.get("brand") and ad.get("model") and ad.get("year")):
            skipped += 1
            continue
        stat, capped = deal_engine.pick_stat(ad, stats, fine, fuel)
        if not stat:
            skipped += 1
            continue
        priced = deal_engine.score_ad(ad, stat, capped)
        updates.append({"ad_id": ad["id"], **priced})

    log.info("recomputed %d deals, skipped %d (no matching comps / missing data)",
              len(updates), skipped)
    db.update_deal_pricing(updates)
    log.info("backfill complete")


if __name__ == "__main__":
    main()

"""Re-check stored ad URLs against their live OLX page. Run: python -m src.url_checker"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from . import config, db, olx_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def run():
    priority_ids = db.deal_ad_ids()
    candidates = db.ads_to_check(config.URL_CHECK_BATCH_SIZE, config.URL_CHECK_LOOKBACK_DAYS, priority_ids)
    log.info("checking %d ad urls (%d are current deals)", len(candidates), len(priority_ids))
    if not candidates:
        return

    now = datetime.now(timezone.utc).isoformat()
    results = []
    with ThreadPoolExecutor(max_workers=config.URL_CHECK_CONCURRENCY) as pool:
        future_to_id = {pool.submit(olx_api.check_offer_status, a["url"]): a["id"] for a in candidates}
        for future in as_completed(future_to_id):
            status = future.result()
            if status != "unknown":
                results.append({"id": future_to_id[future], "url_status": status, "url_checked_at": now})

    db.update_url_status(results)
    log.info("updated %d/%d ad statuses", len(results), len(candidates))


if __name__ == "__main__":
    run()

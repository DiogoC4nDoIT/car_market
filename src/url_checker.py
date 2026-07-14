"""Re-check stored ad URLs against their live OLX page. Run: python -m src.url_checker"""
import logging
import time
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
    # Submissions are paced (not just worker-count-capped): a first attempt at
    # full concurrency (6 workers, no pacing — ~20 req/s) got 403'd on 85% of
    # requests after the first ~300ish, confirmed by status-code logging as an
    # OLX-side rate limit on individual ad-page fetches specifically (the bulk
    # JSON listing API the crawler uses is unaffected). URL_CHECK_DELAY_SECONDS
    # between submissions keeps aggregate rate well under that threshold.
    with ThreadPoolExecutor(max_workers=config.URL_CHECK_CONCURRENCY) as pool:
        future_to_id = {}
        for a in candidates:
            future_to_id[pool.submit(olx_api.check_offer_status, a["url"])] = a["id"]
            time.sleep(config.URL_CHECK_DELAY_SECONDS)
        for future in as_completed(future_to_id):
            status = future.result()
            if status != "unknown":
                results.append({"id": future_to_id[future], "url_status": status, "url_checked_at": now})

    db.update_url_status(results)
    log.info("updated %d/%d ad statuses", len(results), len(candidates))


if __name__ == "__main__":
    run()

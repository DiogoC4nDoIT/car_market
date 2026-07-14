"""Re-check stored ad URLs against their live OLX page. Run: python -m src.url_checker"""
import logging
import time
from datetime import datetime, timezone

from . import config, db, olx_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def run():
    candidates = db.ads_to_check(config.URL_CHECK_BATCH_SIZE, config.URL_CHECK_LOOKBACK_DAYS)
    log.info("checking %d ad urls", len(candidates))
    if not candidates:
        return

    now = datetime.now(timezone.utc).isoformat()
    results = []
    for a in candidates:
        status = olx_api.check_offer_status(a["url"])
        if status != "unknown":
            results.append({"id": a["id"], "url_status": status, "url_checked_at": now})
        time.sleep(1)  # be polite — same pacing fetch_deep_sweep uses between requests

    db.update_url_status(results)
    log.info("updated %d ad statuses", len(results))


if __name__ == "__main__":
    run()

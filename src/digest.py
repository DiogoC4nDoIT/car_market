"""Daily Telegram digest: top active deals found in the last 24 h.

Run: python -m src.digest
"""
import logging
from datetime import datetime, timedelta, timezone

from . import db, notify
from .notify import CONF_EMOJI

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TOP_N = 10


def run():
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    res = (db.client().table("deals_view").select("*")
           .gte("created_at", since).eq("status", "ativo")
           .order("score", desc=True).limit(TOP_N).execute())
    deals = res.data
    if not deals:
        log.info("no active deals in the last 24h; skipping digest")
        return

    lines = [f"📋 <b>Resumo diário — {len(deals)} negócio(s) nas últimas 24 h</b>\n"]
    for i, d in enumerate(deals, 1):
        conf = d.get("confidence") or "?"
        lines.append(
            f"{i}. <a href=\"{d['url']}\">{d['title']}</a>\n"
            f"   💶 {d['price']:.0f} € (mediana {d['median_price']:.0f} €) · "
            f"💰 ~{d['est_profit']:.0f} € · "
            f"{CONF_EMOJI.get(conf, '⚪')} {conf} ({d.get('n') or '?'})"
        )
    notify.send_telegram("\n".join(lines))


if __name__ == "__main__":
    run()

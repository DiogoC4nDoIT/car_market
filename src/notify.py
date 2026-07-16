import logging
import time

import requests

from . import config

log = logging.getLogger(__name__)

CONF_EMOJI = {"alta": "🟢", "media": "🟡", "baixa": "🔴"}
CONF_LABEL = {"alta": "High", "media": "Medium", "baixa": "Low"}


def _post(method: str, payload: dict, retries: int = 3) -> bool:
    """A deal that fails to notify is never re-sent (the crawler filters
    already-inserted deals on later runs), so transient failures — network
    blips, Telegram 5xx, 429 rate limits — are retried here. Other 4xx
    (bad photo URL, bad markup) won't improve on retry and fail immediately,
    letting send_telegram()'s sendPhoto→sendMessage fallback kick in."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"
    for attempt in range(retries):
        wait = 2 ** attempt
        try:
            r = requests.post(url, json=payload, timeout=20)
        except requests.RequestException as e:
            log.warning("Telegram %s %s (attempt %d)", method, type(e).__name__, attempt + 1)
        else:
            if r.ok:
                return True
            if r.status_code == 429:
                try:
                    wait = int(r.json()["parameters"]["retry_after"])
                except (ValueError, KeyError, TypeError):
                    pass
                log.warning("Telegram %s rate-limited (attempt %d), waiting %ds",
                            method, attempt + 1, wait)
            elif r.status_code >= 500:
                log.warning("Telegram %s HTTP %d (attempt %d)", method, r.status_code, attempt + 1)
            else:
                log.error("Telegram %s error: %s", method, r.text)
                return False
        if attempt + 1 < retries:
            time.sleep(wait)
    log.error("Telegram %s failed after %d attempts", method, retries)
    return False


def send_telegram(text: str, photo_url: str | None = None) -> bool:
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        log.warning("Telegram not configured; skipping alert")
        return False
    if photo_url:
        ok = _post("sendPhoto", {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "photo": photo_url,
            "caption": text,
            "parse_mode": "HTML",
        })
        if ok:
            return True
        log.warning("sendPhoto failed; falling back to text message")
    return _post("sendMessage", {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    })


def _links(ad: dict) -> str:
    """Two lines linking out to the ad: our own dashboard detail page (only when
    DASHBOARD_URL is configured) and the source OLX listing."""
    lines = []
    if config.DASHBOARD_URL:
        lines.append(f"🔗 View on Stand: {config.DASHBOARD_URL}/?ad={ad.get('id')}")
    lines.append(f"🔗 View on OLX: {ad.get('url')}")
    return "\n".join(lines)


def format_price_change(ad: dict, old_price: float, new_price: float) -> str:
    arrow = "📉" if new_price < old_price else "📈"
    delta = new_price - old_price
    return (
        f"{arrow} <b>Price change on a favourite</b>\n"
        f"<b>{ad.get('title')}</b>\n"
        f"💶 €{old_price:.0f} → <b>€{new_price:.0f}</b> "
        f"({'+' if delta > 0 else ''}€{delta:.0f})\n"
        f"📅 {ad.get('year')}  |  🛣 {ad.get('mileage') or '?'} km  |  📍 {ad.get('region') or '?'}\n"
        f"{_links(ad)}"
    )


def format_new_match(ad: dict, deal: dict, search_name: str) -> str:
    conf = deal.get("confidence") or "?"
    return (
        f"⭐ <b>New deal on favourite search \"{search_name}\"</b>\n"
        f"<b>{ad.get('title')}</b>\n"
        f"💶 Price: <b>€{deal['price']:.0f}</b> "
        f"(market median: €{deal['median_price']:.0f})\n"
        f"📉 Discount: {deal['discount'] * 100:.0f}%  |  "
        f"💰 Est. profit: ~€{deal['est_profit']:.0f}\n"
        f"{CONF_EMOJI.get(conf, '⚪')} Confidence: {CONF_LABEL.get(conf, conf)} "
        f"({deal.get('n', '?')} comparables)\n"
        f"📅 {ad.get('year')}  |  🛣 {ad.get('mileage') or '?'} km  |  "
        f"⛽ {ad.get('fuel') or '?'}  |  📍 {ad.get('region') or '?'}\n"
        f"{_links(ad)}"
    )

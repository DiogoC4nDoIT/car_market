import logging

import requests

from . import config

log = logging.getLogger(__name__)

CONF_EMOJI = {"alta": "🟢", "media": "🟡", "baixa": "🔴"}


def _post(method: str, payload: dict) -> bool:
    r = requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}",
        json=payload,
        timeout=20,
    )
    if not r.ok:
        log.error("Telegram %s error: %s", method, r.text)
    return r.ok


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


def format_deal(deal: dict, ad: dict) -> str:
    conf = deal.get("confidence") or "?"
    return (
        f"🚗 <b>Possível negócio!</b>\n"
        f"<b>{ad.get('title')}</b>\n"
        f"💶 Preço: <b>{deal['price']:.0f} €</b> "
        f"(mediana do mercado: {deal['median_price']:.0f} €)\n"
        f"📉 Desconto: {deal['discount'] * 100:.0f}%  |  "
        f"💰 Lucro estimado: ~{deal['est_profit']:.0f} €\n"
        f"{CONF_EMOJI.get(conf, '⚪')} Confiança: {conf} "
        f"({deal.get('n', '?')} comparáveis)\n"
        f"📅 {ad.get('year')}  |  🛣 {ad.get('mileage') or '?'} km  |  "
        f"⛽ {ad.get('fuel') or '?'}  |  📍 {ad.get('region') or '?'}\n"
        f"🔗 {ad.get('url')}"
    )

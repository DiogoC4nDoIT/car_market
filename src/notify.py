import logging

import requests

from . import config

log = logging.getLogger(__name__)


def send_telegram(text: str) -> bool:
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        log.warning("Telegram not configured; skipping alert")
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    if not r.ok:
        log.error("Telegram error: %s", r.text)
    return r.ok


def format_deal(deal: dict, ad: dict) -> str:
    return (
        f"🚗 <b>Possível negócio!</b>\n"
        f"<b>{ad.get('title')}</b>\n"
        f"💶 Preço: <b>{deal['price']:.0f} €</b> "
        f"(mediana do mercado: {deal['median_price']:.0f} €)\n"
        f"📉 Desconto: {deal['discount'] * 100:.0f}%  |  "
        f"💰 Lucro estimado: ~{deal['est_profit']:.0f} €\n"
        f"📅 {ad.get('year')}  |  🛣 {ad.get('mileage') or '?'} km  |  "
        f"⛽ {ad.get('fuel') or '?'}  |  📍 {ad.get('region') or '?'}\n"
        f"🔗 {ad.get('url')}"
    )

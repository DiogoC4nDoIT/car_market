"""Flipper deal logic: buy <= BUDGET, resell near market median, no wrenching."""
from . import config


def is_blacklisted(ad: dict) -> bool:
    text = f"{ad.get('title') or ''} {ad.get('_description') or ''}".lower()
    return any(kw in text for kw in config.BLACKLIST_KEYWORDS)


def stats_key(brand, model, year):
    return (str(brand).lower(), str(model).lower(), (int(year) // 2) * 2)


def build_stats_index(rows: list[dict]) -> dict:
    """rows from the market_stats view -> lookup dict."""
    return {
        stats_key(r["brand"], r["model"], r["year_bucket"]): r
        for r in rows
    }


def evaluate(ad: dict, stats: dict) -> dict | None:
    """Return a deals row if this ad is a flip candidate, else None."""
    price = ad.get("price")
    if not price or price < 100 or price > config.BUDGET:
        return None
    if ad.get("is_blacklisted"):
        return None
    if ad.get("mileage") and ad["mileage"] > config.MAX_MILEAGE:
        return None
    if not (ad.get("brand") and ad.get("model") and ad.get("year")):
        return None

    stat = stats.get(stats_key(ad["brand"], ad["model"], ad["year"]))
    if not stat:
        return None

    median = float(stat["median_price"])
    discount = 1 - price / median
    est_profit = median * config.RESALE_FACTOR - price
    if discount < config.MIN_DISCOUNT or est_profit < config.MIN_PROFIT:
        return None

    return {
        "ad_id": ad["id"],
        "price": price,
        "median_price": round(median, 2),
        "discount": round(discount, 4),
        "est_profit": round(est_profit, 2),
        # profit-weighted score, scaled by sample confidence
        "score": round(est_profit * discount * min(stat["n"], 20) / 20, 2),
    }

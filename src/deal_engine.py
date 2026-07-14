"""Flipper deal logic: buy <= BUDGET, resell near market median, no wrenching."""
from . import config


def is_blacklisted(ad: dict) -> bool:
    text = f"{ad.get('title') or ''} {ad.get('_description') or ''}".lower()
    return any(kw in text for kw in config.BLACKLIST_KEYWORDS)


def stats_key(brand, model, year):
    return (str(brand).lower(), str(model).lower(), (int(year) // 2) * 2)


def km_band(mileage: int) -> int:
    """Must match the CASE bucketing in the market_stats_fine view."""
    lo, hi = config.KM_BANDS
    if mileage < lo:
        return 0
    return lo if mileage < hi else hi


def fine_key(brand, model, year, fuel, mileage):
    return (*stats_key(brand, model, year), str(fuel).lower(), km_band(int(mileage)))


def fuel_key(brand, model, year, fuel):
    return (*stats_key(brand, model, year), str(fuel).lower())


def build_stats_index(rows: list[dict]) -> dict:
    """rows from the market_stats view -> lookup dict."""
    return {
        stats_key(r["brand"], r["model"], r["year_bucket"]): r
        for r in rows
    }


def build_fine_index(rows: list[dict]) -> dict:
    """rows from the market_stats_fine view -> lookup dict."""
    return {
        (*stats_key(r["brand"], r["model"], r["year_bucket"]),
         str(r["fuel"]).lower(), int(r["km_band"])): r
        for r in rows
    }


def build_fuel_index(rows: list[dict]) -> dict:
    """rows from the market_stats_fuel view -> lookup dict."""
    return {
        (*stats_key(r["brand"], r["model"], r["year_bucket"]), str(r["fuel"]).lower()): r
        for r in rows
    }


def confidence(stat: dict) -> str:
    """alta/media/baixa from sample size and price spread (IQR / median)."""
    n = int(stat["n"])
    median = float(stat["median_price"])
    rel_iqr = (float(stat["p75"]) - float(stat["p25"])) / median if median else float("inf")
    if n < config.CONF_BAIXA_N or rel_iqr > config.CONF_BAIXA_IQR:
        return "baixa"
    if n >= config.CONF_ALTA_N and rel_iqr <= config.CONF_ALTA_IQR:
        return "alta"
    return "media"


def fingerprint(ad: dict) -> str:
    """Same car re-listed under a new id produces the same fingerprint."""
    return "|".join(str(ad.get(k) or "").lower()
                    for k in ("brand", "model", "year", "mileage", "price"))


def pick_stat(ad: dict, stats: dict, fine_stats: dict | None = None,
              fuel_stats: dict | None = None) -> tuple[dict | None, bool]:
    """Pick the most specific comparable-ads bucket for `ad`, trying:
    fuel + mileage band -> fuel only -> coarse (fuel-blind), in that order.
    Returns (stat, capped) where `capped` means the match isn't fuel+mileage
    specific, so confidence should not be reported as "alta"."""
    if fine_stats and ad.get("fuel") and ad.get("mileage"):
        stat = fine_stats.get(fine_key(ad["brand"], ad["model"], ad["year"],
                                       ad["fuel"], ad["mileage"]))
        if stat is not None:
            return stat, False
    if fuel_stats and ad.get("fuel"):
        stat = fuel_stats.get(fuel_key(ad["brand"], ad["model"], ad["year"], ad["fuel"]))
        if stat is not None:
            return stat, True
    return stats.get(stats_key(ad["brand"], ad["model"], ad["year"])), True


def score_ad(ad: dict, stat: dict, capped: bool) -> dict:
    """Pricing math for `ad` against the chosen comparable-ads `stat` bucket."""
    price = ad["price"]
    median = float(stat["median_price"])
    discount = 1 - price / median
    est_profit = median * config.RESALE_FACTOR - price
    conf = confidence(stat)
    if capped and conf == "alta":
        conf = "media"
    return {
        "median_price": round(median, 2),
        "discount": round(discount, 4),
        "est_profit": round(est_profit, 2),
        # profit-weighted score, scaled by sample confidence
        "score": round(est_profit * discount * min(stat["n"], 20) / 20, 2),
        "n": int(stat["n"]),
        "confidence": conf,
    }


def evaluate(ad: dict, stats: dict, fine_stats: dict | None = None,
             fuel_stats: dict | None = None) -> dict | None:
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

    stat, capped = pick_stat(ad, stats, fine_stats, fuel_stats)
    if not stat:
        return None

    priced = score_ad(ad, stat, capped)
    if priced["discount"] < config.MIN_DISCOUNT or priced["est_profit"] < config.MIN_PROFIT:
        return None

    return {
        "ad_id": ad["id"],
        "price": price,
        **priced,
        "fingerprint": fingerprint(ad),
    }

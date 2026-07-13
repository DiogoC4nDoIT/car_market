"""Token/bandwidth-efficient OLX.pt client.

Uses OLX's public JSON API (the same one the website's frontend calls)
instead of rendering pages with a browser. One request returns 40 ads.
"""
import logging
import re
import time

import requests

log = logging.getLogger(__name__)

BASE = "https://www.olx.pt/api/v1/offers/"
CARROS_PAGE = "https://www.olx.pt/carros-motos-e-barcos/carros/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
LIMIT = 40          # max page size accepted by the API
MAX_OFFSET = 1000   # OLX caps offset; use price buckets to go deeper

# OLX's "carros" category params never include a brand/marca field (only
# "modelo") — brand has to be inferred from the free-text title instead.
_BRANDS = [
    "Alfa Romeo", "Aston Martin", "Audi", "Bentley", "BMW", "BYD", "Chevrolet",
    "Chrysler", "Citroen", "Cupra", "Dacia", "Daihatsu", "Dodge", "DS",
    "Ferrari", "Fiat", "Ford", "Honda", "Hyundai", "Infiniti", "Isuzu", "Iveco",
    "Jaguar", "Jeep", "Kia", "Lada", "Lamborghini", "Lancia", "Land Rover",
    "Lexus", "Maserati", "Mazda", "Mercedes-Benz", "MG", "Mini",
    "Mitsubishi", "Nissan", "Opel", "Peugeot", "Porsche", "Renault", "Rover",
    "Saab", "Seat", "Skoda", "Smart", "SsangYong", "Subaru", "Suzuki", "Tesla",
    "Toyota", "Volkswagen", "Volvo",
]
_BRAND_BY_LOWER = {b.lower(): b for b in _BRANDS}
_BRAND_BY_LOWER["vw"] = "Volkswagen"
_BRAND_BY_LOWER["mercedes"] = "Mercedes-Benz"
_BRAND_BY_LOWER["citroën"] = "Citroen"
_BRAND_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(_BRAND_BY_LOWER, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def guess_brand(title: str) -> str | None:
    m = _BRAND_RE.search(title or "")
    return _BRAND_BY_LOWER[m.group(1).lower()] if m else None


def _get(params: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        r = requests.get(BASE, params=params, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            return r.json()
        log.warning("OLX API %s (attempt %d)", r.status_code, attempt + 1)
        time.sleep(2 ** attempt * 2)
    r.raise_for_status()
    return {}


def discover_category_id() -> int | None:
    """Find the Carros category id from the category page HTML."""
    try:
        r = requests.get(CARROS_PAGE, headers={**HEADERS, "Accept": "text/html"}, timeout=30)
        for pat in (r'"categoryId":\s*"?(\d+)', r'category_id[=:]"?(\d+)'):
            m = re.search(pat, r.text)
            if m:
                return int(m.group(1))
    except Exception as e:
        log.warning("category discovery failed: %s", e)
    return None


def _first_photo(o: dict) -> str | None:
    photos = o.get("photos") or []
    if not photos:
        return None
    # link is a template like ".../image;s={width}x{height}"
    link = photos[0].get("link") or ""
    return link.replace("{width}", "800").replace("{height}", "600") or None


def parse_offer(o: dict) -> dict:
    """Flatten one OLX offer into our ads row."""
    params, price = {}, None
    for p in o.get("params", []):
        key = p.get("key")
        val = p.get("value") or {}
        if key == "price":
            price = val.get("value")
            params["price_label"] = val.get("label")
        else:
            params[key] = val.get("label") or val.get("key")

    def pick(*keys):
        for k in keys:
            if params.get(k):
                return params[k]
        return None

    def num(s):
        if s is None:
            return None
        digits = re.sub(r"[^\d]", "", str(s))
        return int(digits) if digits else None

    return {
        "id": o["id"],
        "url": o.get("url"),
        "photo_url": _first_photo(o),
        "title": o.get("title"),
        "price": price,
        "brand": pick("marca", "brand", "motorbrand", "carbrand") or guess_brand(o.get("title")),
        "model": pick("modelo", "model", "motormodel", "carmodel"),
        "year": num(pick("ano", "year", "anode")),
        "mileage": num(pick("quilometros", "mileage", "kms", "milage")),
        "fuel": pick("combustivel", "fuel", "petrol"),
        "region": (o.get("location") or {}).get("region", {}).get("name")
                  or (o.get("location") or {}).get("city", {}).get("name"),
        "olx_created_at": o.get("created_time"),
        "params": params,
        "_description": o.get("description") or "",
    }


def fetch_page(category_id: int, offset: int = 0,
               price_from: float | None = None,
               price_to: float | None = None) -> list[dict]:
    params = {
        "category_id": category_id,
        "limit": LIMIT,
        "offset": offset,
        "sort_by": "created_at:desc",
        "currency": "EUR",
    }
    if price_from is not None:
        params["filter_float_price:from"] = int(price_from)
    if price_to is not None:
        params["filter_float_price:to"] = int(price_to)
    data = _get(params)
    return [parse_offer(o) for o in data.get("data", [])]


# Price buckets used by the weekly deep sweep to bypass the offset cap.
SWEEP_BUCKETS = [(0, 250), (250, 500), (500, 750), (750, 1000), (1000, 1250),
                 (1250, 1500), (1500, 1750), (1750, 2000), (2000, 2500),
                 (2500, 3000), (3000, 4000), (4000, 5000), (5000, 6000),
                 (6000, 8000), (8000, 10000), (10000, 12500), (12500, 15000)]


def fetch_deep_sweep(category_id: int, price_ceiling: float) -> list[dict]:
    out, seen = [], set()
    for lo, hi in SWEEP_BUCKETS:
        if lo >= price_ceiling:
            break
        for page in range(MAX_OFFSET // LIMIT):
            batch = fetch_page(category_id, page * LIMIT,
                               price_from=lo, price_to=min(hi, price_ceiling))
            if not batch:
                break
            for a in batch:
                if a["id"] not in seen:
                    seen.add(a["id"])
                    out.append(a)
            time.sleep(1)
    return out

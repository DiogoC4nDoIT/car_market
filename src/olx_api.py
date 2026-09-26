"""Token/bandwidth-efficient OLX.pt client.

Uses OLX's public JSON API (the same one the website's frontend calls)
instead of rendering pages with a browser. One request returns 40 ads.
"""
import asyncio
import json
import logging
import re
import threading
import time
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from . import config

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

# Shared connection pool — reused by every request this module makes (list
# pages, category discovery, per-ad status checks) instead of a fresh
# TCP+TLS handshake per call. The mounted Retry handles transient connection
# drops and 5xx responses transparently for all of them; 403/429 are
# deliberately NOT retried here — that's OLX rate-limiting, and hammering it
# makes it worse (url_checker's submission pacing is the real control).
_session = requests.Session()
_session.headers.update(HEADERS)
_session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=3, backoff_factor=1,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods={"GET"},
)))
if config.PROXY_URL:
    _session.proxies.update({"http": config.PROXY_URL, "https": config.PROXY_URL})

# OLX's WAF (AWS CloudFront) blocks non-browser clients from datacenter IPs:
# plain requests from GitHub Actions runners get 403 regardless of headers,
# cookies or egress network (Azure, Cloudflare WARP, Tor — all verified blocked
# 2026-08-24), while a real headless Chrome from the same runner gets 200.
# OLX_BROWSER=1 therefore routes every request through a Playwright Chromium
# page: bootstrap loads the Carros page once, then same-origin fetch() calls
# ride on the browser's TLS/HTTP2 fingerprint, cookies and JS execution.
#
# Playwright's *sync* API is bound to the thread that started it, which is why
# this used to funnel every call through one page on a single-worker executor
# — url_checker's own ThreadPoolExecutor fanned out, but every worker blocked
# on that same page underneath, so a 1500-URL batch ran fully serial (~20-25
# min on GitHub Actions). The *async* API doesn't have that restriction: one
# thread runs an asyncio loop and can genuinely juggle several pages at once,
# each still same-origin (cookies are shared at the browser-context level, so
# any page that has loaded an olx.pt URL can `fetch()` others). Pool size
# matches URL_CHECK_CONCURRENCY — the concurrency the config already declared
# intent for — rather than adding new load OLX hasn't already been sized for.
_JS_FETCH = """async ({url, accept}) => {
    const res = await fetch(url, {headers: {'Accept': accept}});
    return {status: res.status, text: await res.text()};
}"""


class _Browser:
    def __init__(self):
        self._pool_size = max(1, config.URL_CHECK_CONCURRENCY)
        self._start_error = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._start_error:
            raise self._start_error

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_start())
        except Exception as e:
            self._start_error = e
        finally:
            self._ready.set()
        if self._start_error is None:
            self._loop.run_forever()

    async def _async_start(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        browser = await self._pw.chromium.launch(
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(locale="pt-PT", user_agent=HEADERS["User-Agent"])
        self._pages = asyncio.Queue()
        for _ in range(self._pool_size):
            page = await ctx.new_page()
            r = await page.goto(CARROS_PAGE, wait_until="domcontentloaded", timeout=60_000)
            if r is None or r.status != 200:
                raise RuntimeError(f"browser bootstrap got HTTP {r.status if r else '?'}")
            await self._pages.put(page)
        log.info("browser transport ready (%d pages)", self._pool_size)

    async def _afetch(self, url: str, accept: str) -> tuple[int, str]:
        page = await self._pages.get()
        try:
            out = await page.evaluate(_JS_FETCH, {"url": url, "accept": accept})
            return out["status"], out["text"]
        finally:
            self._pages.put_nowait(page)

    def fetch(self, url: str, accept: str) -> tuple[int, str]:
        return asyncio.run_coroutine_threadsafe(self._afetch(url, accept), self._loop).result()


_browser_instance, _browser_lock = None, threading.Lock()


def _browser() -> _Browser:
    global _browser_instance
    with _browser_lock:
        if _browser_instance is None:
            _browser_instance = _Browser()
    return _browser_instance

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
    err, status = None, None
    for attempt in range(retries):
        try:
            if config.OLX_BROWSER:
                status, text = _browser().fetch(BASE + "?" + urlencode(params), "application/json")
                if status == 200:
                    return json.loads(text)
            else:
                r = _session.get(BASE, params=params, timeout=30)
                status = r.status_code
                if status == 200:
                    return r.json()
            err = None
            log.warning("OLX API %s (attempt %d)", status, attempt + 1)
        except Exception as e:  # session-level retries / browser transport exhausted
            err = e
            log.warning("OLX API %s (attempt %d)", type(e).__name__, attempt + 1)
        time.sleep(2 ** attempt * 2)
    # Normalized to a RequestException either way so callers (resolve_category's
    # probe) can catch one type regardless of transport.
    raise requests.HTTPError(
        f"OLX API failed after {retries} attempts (last status {status})"
    ) from err


def discover_category_id() -> int | None:
    """Find the Carros category id from the category page HTML."""
    try:
        if config.OLX_BROWSER:
            _, body = _browser().fetch(CARROS_PAGE, "text/html")
        else:
            body = _session.get(CARROS_PAGE, headers={"Accept": "text/html"}, timeout=30).text
        for pat in (r'"categoryId":\s*"?(\d+)', r'category_id[=:]"?(\d+)'):
            m = re.search(pat, body)
            if m:
                return int(m.group(1))
    except Exception as e:
        log.warning("category discovery failed: %s", e)
    return None


# Every OLX ad page embeds a `window.__PRERENDERED_STATE__ = "<escaped JSON>"`
# blob carrying the same ad object the frontend renders from, including a real
# status/isActive field. This is the only signal check_offer_status() trusts.
#
# An earlier version of this function scraped localized page text instead
# ("anúncio inativo"/"vendido" etc). Verified 2026-07-14 against real pages and
# dropped entirely: OLX ships its *entire* i18n translation table on every page
# load regardless of that ad's actual state, so phrases like "Anúncio inactivo"
# and "já não está disponível" showed up even on a genuinely active ad's page
# (as unrelated inactive-ad-template and chat-widget dictionary entries) — text
# search there isn't "best-effort", it's actively wrong. HTTP 404/410 plus this
# JSON blob are the only checks that held up against real active/removed pages.
_STATE_RE = re.compile(r'window\.__PRERENDERED_STATE__\s*=\s*"(.*?)";\s*\n', re.S)


def _ad_state(body: str) -> dict | None:
    m = _STATE_RE.search(body)
    if not m:
        return None
    try:
        return json.loads(json.loads('"' + m.group(1) + '"')).get("ad", {}).get("ad")
    except (json.JSONDecodeError, ValueError, AttributeError):
        return None


def check_offer_status(url: str) -> str:
    """Fetch an ad's own page and classify it: 'active' | 'sold' | 'removed' | 'unknown'."""
    try:
        if config.OLX_BROWSER:
            code, body = _browser().fetch(url, "text/html")
        else:
            r = _session.get(url, headers={"Accept": "text/html"}, timeout=30)
            code, body = r.status_code, r.text
    except Exception as e:
        log.info("unknown: request exception (%s) for %s", type(e).__name__, url)
        return "unknown"
    if code in (404, 410):
        return "removed"
    if code != 200:
        log.info("unknown: HTTP %d for %s", code, url)
        return "unknown"

    ad = _ad_state(body)
    if ad is None:
        log.info("unknown: no parsable ad state (body len=%d) for %s", len(body), url)
        return "unknown"
    status = (ad.get("status") or "").lower()
    if status == "active" and ad.get("isActive"):
        return "active"
    if status:
        return "sold" if ("sold" in status or "vendid" in status) else "removed"
    return "removed" if ad.get("isActive") is False else "unknown"


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

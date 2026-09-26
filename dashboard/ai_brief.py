"""Optional AI good-deal brief for the Market tab: a short plain-English narration of the best
vetted deals matching the tab's own filter bar (brand/region/fuel/year/price), via Groq's free
tier. Entirely optional — every other Market tab feature works without it, this just hides
itself if GROQ_API_KEY isn't configured."""
import streamlit as st

from dashboard.data import secret

DEFAULT_MODEL = "openai/gpt-oss-20b"

# Built from two 5-persona panel reviews (sourcing/margin, buyer trust, logistics, resale,
# data-skeptic) — first on a single-model version, then on this corrected filter-driven,
# multi-deal version. Converged points baked in here:
# - `deals` are pre-vetted (deal_engine.evaluate(): budget/discount/profit/mileage/blacklist
#   together) — never blend in a weaker, single-axis "cheap vs. its own median" claim.
# - Never let the model touch URLs — it has no browsing access and will mangle/invent OLX
#   links; the app renders real per-deal links separately, in the same order as the prose.
# - Each deal needs a stable label (assigned by the app) so prose and rendered links can't
#   drift apart once several different models are in view at once.
# - Say "estimated profit", never "profit"/"guaranteed" — it's a modeled figure, not a sale.
PROMPT = """You write a short brief (aim for one sentence per deal — more only if there's real \
signal to add, never pad) for someone in Portugal sourcing used cars to resell at a profit. \
Plain English, no bullet points, no markdown. The "deals" list is already fully vetted — each \
one already cleared a budget, discount, estimated-profit, mileage, and blacklist bar together, \
so you don't need to argue whether they're worth considering, only explain why each one \
specifically is priced where it is and what its resale risk looks like.

The app already shows, directly above your text, exactly which filters were applied and how \
many deals matched in total vs. how many are shown to you — do NOT restate, guess, or summarize \
those filter values or counts yourself (you do not even see the filter values, only the already- \
filtered "deals" below); start straight in on the deals themselves.

Strict rules:
- Every number below is ours — state it hedge-free and exactly as given, never invent, round \
differently, or compute a new figure (no averaging discounts, no re-deriving a percentage).
- Refer to each deal ONLY by its given "label" (e.g. "Peugeot 208 (2019) · €1,850") — never \
describe a car in your own words instead of using its label, and never invent a car not in \
the list.
- Say "estimated profit", never "profit" or "guaranteed" — est_profit_eur is a modeled figure \
(median × a resale factor, minus price), not an empirical sale.
- For each deal, fuse two things into one sentence, not two separate restated numbers: (1) WHY \
it's priced right — discount_pct + n_comps/confidence together (e.g. "18% under 14 comps at \
High confidence" reads very differently from "18% under 5 comps at Low confidence"); (2) its \
resale-risk profile — km_band (never a bare mileage_km number) plus days_listed/price_drop_eur \
if present and notable (a long-listed, recently-cut deal signals a motivated seller; a fresh \
listing may not stay available long) — skip the second half if there's nothing notable, to \
protect the length budget.
- If near_miss_count is present, add ONE short aside distinguishing it clearly from the deals \
above, substituting the ACTUAL near_miss_count number (e.g. if near_miss_count is 12, write \
"12 more ads in this filter look cheap by price alone but didn't clear the profit/mileage bar" \
— never write the literal word "near_miss_count" or a placeholder letter, always the real \
number given) — never imply those are additional deals to act on.
- If region_breakdown is present, add ONE short aside on regional spread for these specific \
models/deals — whether the filtered region's prices sit below, at, or above the other regions \
listed — only from region_breakdown, never invent a region not listed, and never state or imply \
a distance/drive-time/"nearby" claim (there's no location data for that here).
- Never write out, invent, or reference a URL — the app renders real clickable links separately, \
directly under your text, in the same order as the deals given to you.

DATA:
"""


def available() -> bool:
    return bool(secret("GROQ_API_KEY"))


@st.cache_data(ttl=1800, show_spinner=False)
def generate_brief(summary: dict) -> str | None:
    """summary is a small dict of already-computed, non-identifying numbers — see market.py's
    filter-driven AI brief section for what's passed in and why. Returns None (never raises) on
    any failure so the caller can just show a fallback caption instead of an error. Shorter TTL
    than the old single-model version (30min vs 1h): the deals list here tracks live filters and
    the crawler's own incremental updates, so it should go stale faster."""
    try:
        from groq import Groq
    except ImportError:
        return None
    api_key = secret("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model=secret("GROQ_MODEL") or DEFAULT_MODEL,
            messages=[{"role": "user", "content": PROMPT + str(summary)}],
            # gpt-oss models spend tokens on hidden reasoning before the visible answer —
            # low reasoning_effort plus generous max_tokens keeps that from truncating a
            # short reply mid-sentence (verified: 150-400 tokens cut off before any text).
            max_tokens=1000,
            temperature=0.4,
            reasoning_effort="low",
        )
        content = resp.choices[0].message.content
        return content.strip() if content else None
    except Exception:
        return None

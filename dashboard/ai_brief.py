"""Optional AI market brief for the Market tab deep-dive: a short plain-English narration of
numbers already computed elsewhere in the tab (budget/region fit, buy-ceiling, comp quality —
no new metric, just narration), via Groq's free tier. Entirely optional — every other Market
tab feature works without it, this just hides itself if GROQ_API_KEY isn't configured."""
import streamlit as st

from dashboard.data import secret

DEFAULT_MODEL = "openai/gpt-oss-20b"

# Built from a 5-persona review (sourcing/margin, buyer trust, logistics, resale, data-skeptic)
# of real sample outputs. Converged points baked in here: never let the model touch URLs (it
# has no browsing access and will mangle/invent OLX links — real links are rendered separately
# in market.py from data already in memory); don't let it call the market "strong" unless the
# ratings actually skew that way (caught in a real sample: 13/54 High+Overpriced still got read
# as bullish); split hedge-free numeric narration from hedged general reliability knowledge.
PROMPT = """You write a short market brief (3-5 sentences — more only if there's real signal to \
add, never pad) for someone in Portugal sourcing a used car to resell at a profit. Plain \
English, no bullet points, no markdown. You don't have to reference every field below — only \
what's actually useful to a buying decision.

Strict rules:
- Every number below (prices, counts, ratings, confidence) is ours — state it hedge-free and \
exactly as given, never invent or round differently.
- deal_rating_counts is our own price-vs-median classification of the ads themselves, never \
buyer/dealer/seller opinion — never attribute it to people.
- Only conclude the market looks good ("strong opportunity", "good stock") if deal_rating_counts \
actually skews Great/Good deal — never say that if it skews Fair/High/Overpriced.
- If confidence_label is "baixa" (low) or active_comps_n is under 8, say so plainly in your \
first sentence before making any price claim — the read is thin.
- If budget_eur is given, say plainly whether it covers this selection (compare to \
p25_eur/asking_median_eur) rather than just restating the numbers.
- If target_region is given and region_breakdown lists other regions, say whether stock is \
concentrated near the target region or elsewhere — only from region_breakdown, never invent a \
region not listed.
- If comps_in_budget or comps_in_region is present and is 0, say plainly there's no stock in \
that budget/region right now rather than describing the wider sample optimistically.
- top_comps (if given) are real specific ads — reference them generically ("the cheapest of \
these...") but NEVER write out a URL, invent one, or claim one wasn't given — the app shows \
real links separately, underneath your text.
- You may add ONE short sentence of general, well-known reliability/inspection guidance for \
this specific brand+model+generation, drawn from your own knowledge — keep it hedged \
("commonly", "worth checking") and omit it entirely if you're not genuinely confident about \
that generation; a wrong specific claim is worse than none.

DATA:
"""


def available() -> bool:
    return bool(secret("GROQ_API_KEY"))


@st.cache_data(ttl=3600, show_spinner=False)
def generate_brief(summary: dict) -> str | None:
    """summary is a small dict of already-computed, non-identifying numbers — see market.py's
    deep-dive for what's passed in and why. Returns None (never raises) on any failure so the
    caller can just show a fallback caption instead of an error."""
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
            max_tokens=800,
            temperature=0.4,
            reasoning_effort="low",
        )
        content = resp.choices[0].message.content
        return content.strip() if content else None
    except Exception:
        return None

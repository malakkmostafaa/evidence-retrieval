"""WS3 - leakage filters (WD2, WD3). Each filter returns a reason string (why a page is removed) or None (kept)."""
from __future__ import annotations

from evret.audit import is_factcheck, normalize_url
from evret.urls import canonical, url_variants
from evret.web.schema import ClaimContext

# outcome labels of the date filter
DATED_LE, DATED_AFTER, UNKNOWN = "dated_le", "dated_after", "unknown"


def exclusion_set(ctx: ClaimContext) -> frozenset:
    """Normalised forms (as given + unwrapped) of every URL the claim's own article/source can be stored under."""
    out = set()
    for u in ctx.exclude_urls:
        out |= url_variants(u)
    return frozenset(out)


def url_reason(url: str, ctx: ClaimContext, final_url: str | None = None) -> str | None:
    """Own article / original source (WD3, always) and flagged fact-check domain (main condition). Checked before and after fetching
    (final_url = where a redirect ended)."""
    excl = exclusion_set(ctx)
    for u in (url, final_url):
        if not u:
            continue
        if url_variants(u) & excl:
            return "own_article"
    if not ctx.include_factcheck:
        for u in (url, final_url):
            if u and (is_factcheck(normalize_url(u)) or is_factcheck(canonical(u))):
                return "factcheck"
    return None


def _earliest(d: str) -> str:
    """'YYYY-MM' -> 'YYYY-MM-01', 'YYYY-MM-DD' unchanged (same rule as the corpus not_after filter, D5)."""
    return d + "-01" if d.count("-") == 1 else d


def date_class(pub_date: str, date_source: str, claim_date: str | None) -> str:
    """dated_le | dated_after | unknown. A Wayback snapshot is <= the claim date by construction."""
    if date_source == "wayback":
        return DATED_LE
    if not pub_date:
        return UNKNOWN
    if claim_date is None:
        return DATED_LE
    return DATED_LE if _earliest(pub_date) <= claim_date else DATED_AFTER


def date_reason(pub_date: str, date_source: str, ctx: ClaimContext) -> tuple[str, str | None]:
    """-> (class, reason|None). Unknown dates: removed in the main condition, kept in the lenient ablation."""
    c = date_class(pub_date, date_source, ctx.claim_date)
    if c == DATED_AFTER:
        return c, "dated_after"
    if c == UNKNOWN and not ctx.lenient_dates and ctx.claim_date is not None:
        return c, "date_unknown"
    return c, None

"""URL canonicalisation for exclusion and gold matching.

AVeriTeC stores many URLs as Wayback-Machine wrappers (https://web.archive.org/web/<timestamp>[flags]/<original URL>).
dev.json's fact_checking_article is ALWAYS such a wrapper, while a store may hold the same page under its original URL
(or the other way round). Matching on the normalised wrapper therefore misses the page: in the Block 1 audit the check
"fact-checking article in any store" reported 0, but after unwrapping 17 of the 180 pooled claims' articles are in the pool.
`url_variants` returns both forms so that either side matches.
"""
from __future__ import annotations

import re

from evret.audit import normalize_url

_WAYBACK = re.compile(r"^(?:https?://)?(?:www\.)?web\.archive\.org/web/\d+[a-z_]*/(.+)$", re.I)
_WAYBACK_NORM = re.compile(r"^web\.archive\.org/web/\d+[a-z_]*/(.+)$", re.I)


def unwrap(url: str) -> str:
    """Original URL inside a Wayback wrapper (raw or normalised form); other URLs are returned unchanged."""
    m = _WAYBACK.match(url or "") or _WAYBACK_NORM.match(url or "")
    return m.group(1) if m else (url or "")


def canonical(url: str) -> str:
    """Normalised URL of the unwrapped original ('' for an empty URL)."""
    u = unwrap(url)
    if re.match(r"^https?:/[^/]", u):                 # normalisation of the wrapper collapsed '//' to '/'
        u = re.sub(r"^(https?:)/", r"\1//", u)
    return normalize_url(u) if u else ""


def url_variants(url: str) -> set[str]:
    """All normalised forms under which the same page may be stored: as given and unwrapped."""
    out = {normalize_url(url), canonical(url)} if url else set()
    out.discard("")
    return out

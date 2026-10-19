"""WebHit: the corpus `Hit` plus the web-specific fields. The later shared cross-encoder reads: text, url, domain, pub_date,
date_source, the three scores, chunk_id / doc_id, source. Corpus modules are not modified; this subclasses their dataclass."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from evret.search import Hit


def stable_id(*parts) -> int:
    """63-bit id from strings/ints (the corpus uses sequential ints; web ids must not depend on arrival order)."""
    h = hashlib.blake2b("\x1f".join(str(p) for p in parts).encode("utf-8", "surrogatepass"), digest_size=8).digest()
    return int.from_bytes(h, "big") >> 1


@dataclass
class WebHit(Hit):
    source: str = "web"
    fetched_from: str = ""                 # "live" | "wayback"
    wayback_timestamp: str = ""
    engine: str = ""
    engine_rank: int = 0
    fetch_status: str = ""
    page_hash: str = ""                    # sha256 of the raw bytes
    fetch_time: float = 0.0
    hybrid_score: float | None = None      # RRF score (== score)
    n_tokens: int = 0
    html_date: str = ""
    vector: object = None                  # float16 passage vector, so a reranker/other scorer need not re-embed

"""Shared small types of the web tool."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Mode(str, enum.Enum):
    LIVE = "live"        # cache first, network on a miss
    REPLAY = "replay"    # cache only; a miss is an error (no network call is ever made)


class ReplayMiss(RuntimeError):
    """REPLAY mode asked for something that is not in the cache."""


@dataclass(frozen=True)
class SearchResult:
    """One engine result. engine = the backend that was asked (ddgs) or reported (SearXNG)."""
    url: str
    title: str
    snippet: str
    engine: str
    engine_rank: int            # 1-based position in the engine's list


@dataclass
class ClaimContext:
    """What the evaluation layer gives the tool. No gold labels or gold URLs ever go in here."""
    claim_date: str | None = None                    # "YYYY-MM-DD"
    exclude_urls: frozenset = frozenset()            # raw URLs (wrapped or not) of the claim's own article/source
    lenient_dates: bool = False                      # ablation: keep pages whose date is unknown
    include_factcheck: bool = False                  # ablation: keep flagged fact-check domains
    extra: dict = field(default_factory=dict)

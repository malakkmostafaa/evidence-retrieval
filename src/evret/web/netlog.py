"""Log of every network call (WD7). One JSON object per line, also kept in memory for counting."""
from __future__ import annotations

import json
import threading
import time


class NetLog:
    def __init__(self, path: str | None = None, clock=time.time):
        self.path, self.clock, self.records = path, clock, []
        self._lock = threading.Lock()              # fetches run in several threads

    def log(self, kind: str, target: str, status, seconds: float, **extra):
        rec = {"t": self.clock(), "kind": kind, "target": target, "status": status, "seconds": round(seconds, 4), **extra}
        with self._lock:
            self.records.append(rec)
            if self.path:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def count(self, kind: str | None = None) -> int:
        return sum(1 for r in self.records if kind is None or r["kind"] == kind)

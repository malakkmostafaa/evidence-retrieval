"""WD6 - page cache: SQLite metadata + zlib-compressed blob files (raw bytes by content hash).

Tables (derived tables for extraction / chunks are added by the stages that need them, via `ensure_table`):
  pages    key = "<url>|<wayback timestamp or live>"  -> status, http status, content type, final url, raw hash, fetch time
  lookups  key = "<url>|<claim date>"                -> Wayback CDX answer (timestamp or none), so lookups are replayable
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import uuid
import zlib
from dataclasses import dataclass


def page_key(url: str, wayback_ts: str | None) -> str:
    return f"{url}|{wayback_ts or 'live'}"


@dataclass
class PageRecord:
    key: str
    url: str
    wayback_ts: str | None
    status: str                 # ok | http_<code> | robots_blocked | too_large | timeout | error:<Type>
    http_status: int | None
    content_type: str
    final_url: str
    raw_hash: str | None        # sha256 hex of the raw bytes (None when nothing was stored)
    size: int
    fetch_time: float


class PageCache:
    def __init__(self, root: str):
        self.root = root
        os.makedirs(os.path.join(root, "blobs"), exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(os.path.join(root, "pages.sqlite"), check_same_thread=False)
        with self.lock:
            self.db.execute("CREATE TABLE IF NOT EXISTS pages (key TEXT PRIMARY KEY, url TEXT, wayback_ts TEXT, status TEXT, "
                            "http_status INTEGER, content_type TEXT, final_url TEXT, raw_hash TEXT, size INTEGER, fetch_time REAL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS lookups (key TEXT PRIMARY KEY, url TEXT, claim_date TEXT, "
                            "timestamp TEXT, original TEXT, looked_up REAL)")
            self.db.commit()

    # ---- pages
    def get_page(self, key: str) -> PageRecord | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM pages WHERE key=?", (key,)).fetchone()
        return PageRecord(*row) if row else None

    def put_page(self, rec: PageRecord, body: bytes | None):
        if body is not None:
            p = self._blob_path(rec.raw_hash)
            if not os.path.exists(p):
                os.makedirs(os.path.dirname(p), exist_ok=True)
                tmp = f"{p}.{uuid.uuid4().hex}.tmp"                  # unique: two threads may store the same content
                with open(tmp, "wb") as f:
                    f.write(zlib.compress(body, 6))
                try:
                    os.replace(tmp, p)
                except OSError:                                          # Windows: another thread just stored the same content
                    if not os.path.exists(p):
                        raise
                    os.remove(tmp)
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (rec.key, rec.url, rec.wayback_ts, rec.status, rec.http_status, rec.content_type,
                             rec.final_url, rec.raw_hash, rec.size, rec.fetch_time))
            self.db.commit()

    def get_body(self, raw_hash: str) -> bytes:
        with open(self._blob_path(raw_hash), "rb") as f:
            return zlib.decompress(f.read())

    def _blob_path(self, h: str) -> str:
        return os.path.join(self.root, "blobs", h[:2], h)

    @staticmethod
    def sha256(b: bytes) -> str:
        return hashlib.sha256(b).hexdigest()

    # ---- wayback lookups
    def get_lookup(self, url: str, claim_date: str):
        """-> (found, timestamp|None, original|None); found=False means 'never looked up'."""
        with self.lock:
            row = self.db.execute("SELECT timestamp, original FROM lookups WHERE key=?", (f"{url}|{claim_date}",)).fetchone()
        return (False, None, None) if row is None else (True, row[0], row[1])

    def put_lookup(self, url, claim_date, timestamp, original, now):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO lookups VALUES (?,?,?,?,?,?)",
                            (f"{url}|{claim_date}", url, claim_date, timestamp, original, now))
            self.db.commit()

    def ensure_table(self, ddl: str):
        with self.lock:
            self.db.execute(ddl)
            self.db.commit()

    def execute(self, sql: str, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.fetchall()

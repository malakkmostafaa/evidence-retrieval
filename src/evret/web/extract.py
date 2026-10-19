"""WS3 - text and date extraction (WD4, WD2).

HTML main text: trafilatura (default settings, no comments). PDF: pypdf (WQ2), all pages up to MAX_PDF_PAGES; if a PDF has more
pages the cut is recorded in `note` (never silent). Dates, in this order:
  1. a Wayback snapshot: pub_date = snapshot day (an UPPER bound of the publication date), date_source "wayback";
  2. htmldate on the raw HTML (original date preferred), date_source "htmldate";
  3. a date in the URL path (evret.audit.url_date), date_source "url";
  4. nothing: pub_date "", date_source "none".
The htmldate answer of a snapshot is also kept in `html_date` (not used for filtering) for the manual review.
"""
from __future__ import annotations

import datetime
import io
import logging
from dataclasses import dataclass

from evret.audit import url_date

EXTRACTOR_VERSION = "trafilatura+pypdf+htmldate-v1"
MAX_PDF_PAGES = 300
logging.getLogger("htmldate").setLevel(logging.CRITICAL)
logging.getLogger("trafilatura").setLevel(logging.CRITICAL)
logging.getLogger("pypdf").setLevel(logging.CRITICAL)


@dataclass
class Extracted:
    text: str
    kind: str                   # html | pdf | other
    title: str
    pub_date: str               # "YYYY-MM-DD", "YYYY-MM" or ""
    date_source: str            # wayback | htmldate | url | none
    html_date: str = ""         # what htmldate said (kept even when a snapshot date is used)
    note: str = ""


def is_pdf_bytes(body: bytes, content_type: str, url: str) -> bool:
    return body[:5] == b"%PDF-" or "pdf" in (content_type or "").lower() or url.lower().split("?")[0].endswith(".pdf")


def decode_html(body: bytes) -> str:
    for enc in ("utf-8",):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            pass
    return body.decode("latin-1", "replace") if b"\x00" not in body[:2000] else body.decode("utf-8", "replace")


def pdf_text(body: bytes) -> tuple[str, str]:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(body))
    n = len(r.pages)
    pages = []
    for i in range(min(n, MAX_PDF_PAGES)):
        try:
            pages.append(r.pages[i].extract_text() or "")
        except Exception:
            pages.append("")
    note = f"pdf_pages_read={min(n, MAX_PDF_PAGES)}/{n}" if n > MAX_PDF_PAGES else ""
    return "\n\n".join(p.strip() for p in pages if p.strip()), note


def html_text(html: str, url: str) -> tuple[str, str]:
    import trafilatura
    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True, output_format="txt") or ""
    meta = trafilatura.extract_metadata(html, default_url=url)
    return text, (meta.title if meta and meta.title else "")


def find_html_date(html: str, url: str) -> str:   # url is deliberately NOT passed: htmldate would read the URL path itself and label it "htmldate"
    from htmldate import find_date
    try:
        d = find_date(html, original_date=True, outputformat="%Y-%m-%d", max_date=datetime.date.today().isoformat())
    except Exception:
        d = None
    return d or ""


def extract(body: bytes, content_type: str, url: str, wayback_ts: str | None = None) -> Extracted:
    if is_pdf_bytes(body, content_type, url):
        try:
            text, note = pdf_text(body)
        except Exception as e:
            return Extracted("", "pdf", "", *_date("", url, wayback_ts), note=f"pdf_error:{type(e).__name__}")
        pub, src = _date("", url, wayback_ts)
        return Extracted(text, "pdf", "", pub, src, note=note)
    ct = (content_type or "").lower()
    if ct and not any(x in ct for x in ("html", "xml", "text/plain")):
        return Extracted("", "other", "", *_date("", url, wayback_ts), note=f"unsupported_type:{ct[:40]}")
    html = decode_html(body)
    text, title = html_text(html, url)
    hd = find_html_date(html, url)
    pub, src = _date(hd, url, wayback_ts)
    return Extracted(text, "html", title, pub, src, html_date=hd)


def _date(html_date: str, url: str, wayback_ts: str | None) -> tuple[str, str]:
    if wayback_ts:
        return f"{wayback_ts[:4]}-{wayback_ts[4:6]}-{wayback_ts[6:8]}", "wayback"
    if html_date:
        return html_date, "htmldate"
    u = url_date(url)
    return (u, "url") if u else ("", "none")

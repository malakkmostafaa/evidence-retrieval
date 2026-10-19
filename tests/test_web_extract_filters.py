"""WS3 tests: hand-built pages dated before / after / unknown, a PDF built byte by byte, and the leakage filters."""
import os

from evret.web.extract import extract, is_pdf_bytes
from evret.web.filters import date_class, date_reason, url_reason
from evret.web.schema import ClaimContext

FIX = os.path.join(os.path.dirname(__file__), "web_fixtures", "pages")


def page(name):
    return open(os.path.join(FIX, name), "rb").read()


def make_pdf(pages):
    """Minimal valid PDF, one Helvetica text line per page, with a correct xref table."""
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    kids = []
    for i, t in enumerate(pages):
        pn, cn = 4 + 2 * i, 5 + 2 * i
        kids.append(f"{pn} 0 R")
        stream = f"BT /F1 12 Tf 72 720 Td ({t}) Tj ET".encode()
        objs[pn] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {cn} 0 R "
                    f"/Resources << /Font << /F1 3 0 R >> >> >>").encode()
        objs[cn] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
    objs[2] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode()
    out, offs = b"%PDF-1.4\n", {}
    for n in sorted(objs):
        offs[n] = len(out)
        out += b"%d 0 obj\n" % n + objs[n] + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for n in sorted(objs):
        out += b"%010d 00000 n \n" % offs[n]
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


# ------------------------------------------------------------------------------------------------ extraction
def test_html_before_text_title_and_date():
    e = extract(page("article_before.html"), "text/html", "https://news.example/story")
    assert e.kind == "html" and e.title == "City council approves new bike lanes"
    assert "forty kilometres of protected bike lanes" in e.text and "twelve million dollars" in e.text
    assert "Copyright Example News" not in e.text                      # boilerplate footer is not main text
    assert (e.pub_date, e.date_source) == ("2019-03-01", "htmldate")


def test_reader_comments_are_not_part_of_the_text():
    html = page("article_before.html").decode().replace("</article>", """</article>
<div id="comments" class="comments"><h3>Comments</h3><div class="comment"><p>Great stuff, I totally agree with everything said here, posted by reader42.</p></div></div>""")
    assert "reader42" not in extract(html.encode(), "text/html", "https://news.example/s").text


def test_html_after_date_and_undated_page():
    assert extract(page("article_after.html"), "text/html", "https://news.example/story").pub_date == "2021-05-10"
    e = extract(page("article_undated.html"), "text/html", "https://news.example/story")
    assert (e.pub_date, e.date_source) == ("", "none") and "forty kilometres" in e.text


def test_url_date_is_the_fallback_when_the_page_has_no_date():
    e = extract(page("article_undated.html"), "text/html", "https://news.example/2018/07/05/story")
    assert (e.pub_date, e.date_source) == ("2018-07-05", "url")


def test_wayback_snapshot_date_wins_and_html_date_is_kept_separately():
    e = extract(page("article_after.html"), "text/html", "https://news.example/story", wayback_ts="20200102030405")
    assert (e.pub_date, e.date_source, e.html_date) == ("2020-01-02", "wayback", "2021-05-10")


def test_pdf_text_in_page_order_and_detection():
    pdf = make_pdf(["Alpha page one", "Beta page two"])
    e = extract(pdf, "application/pdf", "https://x.example/report")
    assert e.kind == "pdf" and e.text.index("Alpha page one") < e.text.index("Beta page two")
    assert is_pdf_bytes(pdf, "", "https://x.example/r") and is_pdf_bytes(b"x", "", "https://x.example/r.PDF?x=1")
    assert not is_pdf_bytes(b"<html>", "text/html", "https://x.example/r")
    assert extract(pdf, "application/pdf", "https://x.example/2017/03/report.pdf").pub_date == "2017-03"


def test_broken_pdf_and_unsupported_type_give_empty_text_with_a_note():
    e = extract(b"%PDF-1.4 garbage", "application/pdf", "https://x.example/a.pdf")
    assert e.text == "" and e.note.startswith("pdf_error")
    e = extract(b"\x89PNG....", "image/png", "https://x.example/a.png")
    assert e.text == "" and e.kind == "other" and e.note.startswith("unsupported_type")


# ------------------------------------------------------------------------------------------------ date filter
def test_date_class_table():
    c = "2020-03-10"
    cases = [("2020-03-10", "htmldate", "dated_le"),       # same day counts as before (<=)
             ("2020-03-11", "htmldate", "dated_after"),
             ("2020-03", "url", "dated_le"),                # partial: earliest possible day 03-01 <= 03-10 (same rule as corpus D5)
             ("2020-04", "url", "dated_after"),
             ("", "none", "unknown"),
             ("2025-01-01", "wayback", "dated_le")]         # snapshot date is <= claim date by construction
    assert [date_class(p, s, c) for p, s, _ in cases] == [x[2] for x in cases]


def test_unknown_date_removed_in_main_kept_in_lenient_and_dated_after_always_removed():
    main, lenient = ClaimContext(claim_date="2020-03-10"), ClaimContext(claim_date="2020-03-10", lenient_dates=True)
    assert date_reason("", "none", main) == ("unknown", "date_unknown")
    assert date_reason("", "none", lenient) == ("unknown", None)
    assert date_reason("2021-01-01", "htmldate", lenient) == ("dated_after", "dated_after")
    assert date_reason("2019-01-01", "htmldate", main) == ("dated_le", None)
    assert date_reason("", "none", ClaimContext(claim_date=None)) == ("unknown", None)     # no claim date -> nothing to compare


# ------------------------------------------------------------------------------------------------ url filters
OWN = "https://web.archive.org/web/20200101120000/https://www.example.com/fc/article-1/"


def test_own_article_is_matched_wrapped_unwrapped_and_after_redirect():
    ctx = ClaimContext(exclude_urls=frozenset({OWN}))
    for u in ("https://example.com/fc/article-1", "http://www.example.com/fc/article-1/?utm_source=x", OWN,
              "https://web.archive.org/web/20210101000000/http://example.com/fc/article-1"):
        assert url_reason(u, ctx) == "own_article", u
    assert url_reason("https://example.com/fc/article-2", ctx) is None
    assert url_reason("https://short.example/r", ctx, final_url="https://www.example.com/fc/article-1/") == "own_article"


def test_factcheck_domains_removed_in_main_kept_in_ablation_and_own_article_wins():
    main, abl = ClaimContext(), ClaimContext(include_factcheck=True)
    snopes = "https://www.snopes.com/fact-check/some-claim/"
    assert url_reason(snopes, main) == "factcheck" and url_reason(snopes, abl) is None
    assert url_reason("https://web.archive.org/web/2020/" + snopes, main) == "factcheck"
    assert url_reason("https://web.archive.org/web/2020/https://www.snopes.com/ratings/x", main) == "factcheck"   # host only visible after unwrapping
    assert url_reason("https://example.org/news/story", main) is None
    own = ClaimContext(exclude_urls=frozenset({snopes}), include_factcheck=True)
    assert url_reason(snopes, own) == "own_article"                      # own article is excluded even in the ablation

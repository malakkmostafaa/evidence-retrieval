from evret.audit import normalize_url
from evret.urls import canonical, unwrap, url_variants

W = "https://web.archive.org/web/20201130144023/https://checkyourfact.com/2020/11/03/fact-check-x/"


def test_unwrap_and_variants():
    assert unwrap(W) == "https://checkyourfact.com/2020/11/03/fact-check-x/"
    assert unwrap("https://a.com/p") == "https://a.com/p" and unwrap("") == ""
    assert canonical(W) == "checkyourfact.com/2020/11/03/fact-check-x"
    assert canonical(normalize_url(W)) == "checkyourfact.com/2020/11/03/fact-check-x"      # also from the normalised form
    assert url_variants(W) == {normalize_url(W), "checkyourfact.com/2020/11/03/fact-check-x"}
    assert url_variants("https://www.a.com/x/") == {"a.com/x"}
    assert url_variants("") == set()
    assert canonical("http://web.archive.org/web/2020im_/http://www.a.com/x?utm_source=1") == "a.com/x"

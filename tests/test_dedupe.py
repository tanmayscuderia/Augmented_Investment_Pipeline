"""Domain/name normalization and candidate deduplication."""

from helpers import candidate
from investment_pipeline.sourcing.dedupe import dedupe_candidates, normalize_domain, normalize_name


def test_domain_normalization():
    assert normalize_domain("https://www.foo.ai/about") == "foo.ai"
    assert normalize_domain("http://foo.ai") == "foo.ai"
    assert normalize_domain("https://foo.ai:8080/x") == "foo.ai"
    assert normalize_domain("foo.ai") == "foo.ai"
    assert normalize_domain("") is None
    assert normalize_domain(None) is None


def test_name_normalization_strips_legal_suffixes():
    assert normalize_name("Acme AI, Inc.") == "acme ai"
    assert normalize_name("Foo Bar LLC") == "foo bar"
    assert normalize_name("Ramp") == "ramp"


def test_dedupe_merges_same_domain_from_yc_and_hn():
    yc = candidate()
    hn = candidate(id="hn-acme", source_refs=["https://news.ycombinator.com/item?id=1"])
    merged = dedupe_candidates([yc, hn])
    assert len(merged) == 1
    assert len(merged[0].source_refs) == 2


def test_dedupe_keeps_distinct_domains():
    a = candidate()
    b = candidate(id="other", normalized_domain="other.com", website="https://other.com")
    assert len(dedupe_candidates([a, b])) == 2


def test_dedupe_falls_back_to_normalized_name():
    a = candidate(normalized_domain=None, website=None)
    b = candidate(
        id="acme-hn", normalized_domain=None, website=None, source_refs=["https://news.ycombinator.com/item?id=2"]
    )
    assert len(dedupe_candidates([a, b])) == 1

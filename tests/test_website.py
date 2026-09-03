"""Website extraction and internal-link selection (fixture HTML, no network)."""

from investment_pipeline.config import ROOT
from investment_pipeline.research.website import _select_internal_links, extract_text, page_title

HOMEPAGE = ROOT / "tests" / "fixtures" / "homepage.html"


def test_link_selection_prefers_useful_pages():
    links = _select_internal_links(HOMEPAGE.read_text(), "https://acme.com", max_pages=3)
    paths = [link.rstrip("/").split("acme.com")[-1] for link in links]
    assert "/about" in paths
    assert "/team" in paths
    assert "/customers" in paths
    assert "/blog" not in paths
    assert "/careers" not in paths


def test_external_links_are_ignored():
    links = _select_internal_links(HOMEPAGE.read_text(), "https://acme.com", max_pages=10)
    assert all("twitter.com" not in link for link in links)


def test_text_and_title_extraction():
    html = HOMEPAGE.read_text()
    text = extract_text(html)
    assert text and "bookkeeping" in text.lower()
    assert page_title(html) == "Acme - AI bookkeeping for SMBs"

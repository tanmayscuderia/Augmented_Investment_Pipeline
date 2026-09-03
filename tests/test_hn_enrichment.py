"""HN story matching: common-word names must not capture unrelated stories."""

from helpers import candidate
from investment_pipeline.research.hn_enrichment import _story_matches


def test_domain_match_is_the_strong_signal():
    c = candidate(normalized_name="trope", normalized_domain="trope.ai")
    hit = {"url": "https://trope.ai/post", "title": "Something unrelated"}
    assert _story_matches(hit, c)


def test_common_word_name_does_not_match_unrelated_stories():
    c = candidate(normalized_name="trope", normalized_domain="trope.ai")
    for title in (
        "The Soap Bubble Trope",
        "TropeTwist: narrative structure generation",
        "The Fanfic Sex Trove That Caught an AI",
    ):
        assert not _story_matches({"url": "", "title": title}, c), title


def test_launch_shaped_titles_match():
    c = candidate(normalized_name="trope", normalized_domain="trope.ai")
    assert _story_matches({"url": "", "title": "Show HN: Trope - AI agents for ERPs"}, c)
    assert _story_matches({"url": "", "title": "Trope launches AI FDE for ERP systems"}, c)

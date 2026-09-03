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


def test_three_letter_names_do_not_match_by_title():
    # Real failure: "Qlo" (getqlo.com, insurance AI) matched a 2020 clothing "QLO" Show HN.
    c = candidate(normalized_name="qlo", normalized_domain="getqlo.com")
    stale = {"url": "", "title": "Show HN: QLO - Browser-based 3D clothing mockup builder",
             "created_at": "2020-12-28T10:00:00Z"}
    recent = {"url": "", "title": "Show HN: Qlo - AI for commercial underwriting",
              "created_at": "2026-08-01T10:00:00Z"}
    # 3-letter names never match by title (collision-prone), recent or not
    assert not _story_matches(stale, c)
    assert not _story_matches(recent, c)
    # but a domain match always wins, regardless of name length
    domain_hit = {"url": "https://getqlo.com/post", "title": "Something unrelated",
                  "created_at": "2020-12-28T10:00:00Z"}
    assert _story_matches(domain_hit, c)


def test_story_linking_to_another_domain_is_rejected():
    # Real failure: raindrop.ai collected raindrop.io (bookmarking app) stories.
    c = candidate(normalized_name="raindrop", normalized_domain="raindrop.ai")
    other = {"url": "https://raindrop.io/post", "title": "Raindrop 5.0"}
    assert not _story_matches(other, c)
    # a foreign-domain Show HN that merely mentions the word is also rejected
    foreign = {"url": "https://calmjobs.io",
               "title": "Show HN: CalmJobs - work-life balance jobs"}
    assert not _story_matches(foreign, c)


def test_name_only_match_requires_strict_launch_shape():
    c = candidate(normalized_name="raindrop", normalized_domain="raindrop.ai")
    assert not _story_matches({"url": "", "title": "Thoughts on Evals"}, c)
    assert not _story_matches({"url": "", "title": "The Raindrop theory of memory"}, c)
    ok = {"url": "", "title": "Raindrop: AI monitoring for AI agents",
          "created_at": "2026-08-01T10:00:00Z"}
    assert _story_matches(ok, c)

"""Tests for KB matching and section selection."""

from __future__ import annotations

import pytest

from curio.knowledge_base import KBApp, match_app, select_content


# --- match_app tests ---


def _make_app(name: str, window_titles: list[str]) -> KBApp:
    return KBApp(name=name, window_titles=window_titles, overview="overview")


class TestMatchApp:
    def test_substring_match(self):
        app = _make_app("WA", ["Wild Apricot"])
        assert match_app("Wild Apricot - Events", [app]) is app

    def test_no_match_returns_none(self):
        app = _make_app("WA", ["Wild Apricot"])
        assert match_app("Google Chrome", [app]) is None

    def test_case_insensitive(self):
        app = _make_app("WA", ["Wild Apricot"])
        assert match_app("WILD APRICOT - DASHBOARD", [app]) is app

    def test_first_match_wins(self):
        app1 = _make_app("First", ["Chrome"])
        app2 = _make_app("Second", ["Chrome"])
        assert match_app("Google Chrome", [app1, app2]) is app1

    def test_empty_app_list(self):
        assert match_app("anything", []) is None

    def test_empty_window_title(self):
        app = _make_app("WA", ["Wild Apricot"])
        assert match_app("", [app]) is None


# --- select_content tests ---


def _make_kb(overview: str, sections: list[tuple[str, str]] | None = None) -> KBApp:
    return KBApp(
        name="TestApp",
        window_titles=["Test"],
        overview=overview,
        sections=sections or [],
    )


class TestSelectContent:
    def test_small_kb_all_content(self):
        app = _make_kb(
            "O" * 100,
            [("a.md", "A" * 200), ("b.md", "B" * 200)],
        )
        result = select_content(app, "some transcript", budget_chars=60_000)
        assert "O" * 100 in result
        assert "A" * 200 in result
        assert "B" * 200 in result

    def test_over_budget_top_sections(self):
        app = _make_kb(
            "O" * 100,
            [
                ("a.md", "A" * 25_000),
                ("b.md", "B" * 25_000),
                ("c.md", "C" * 25_000),
            ],
        )
        # budget = 60000, overview = 100, remaining = 59900
        # total sections = 75000 > 59900 -> over budget
        # Need transcript keywords to rank; give keywords matching all equally
        result = select_content(app, "keyword", budget_chars=60_000)
        assert "O" * 100 in result
        # At most 2 sections fit (2 * 25000 = 50000 <= 59900)
        section_count = sum(1 for ch in "ABC" if ch * 25_000 in result)
        assert section_count == 2

    def test_transcript_keyword_ranking(self):
        app = _make_kb(
            "overview",
            [
                ("events.md", "# Adding Events\ncontent about events"),
                ("membership.md", "# Managing Members\ncontent about members"),
            ],
        )
        # Budget tight enough to force selection of only 1 section
        overview_len = len("overview")
        section1_len = len("# Adding Events\ncontent about events")
        section2_len = len("# Managing Members\ncontent about members")
        # Set budget so only overview + 1 section fits
        budget = overview_len + max(section1_len, section2_len) + 5
        result = select_content(app, "how do I add an event", budget_chars=budget)
        assert "Adding Events" in result
        # membership should NOT be included (lower score + no room)
        assert "Managing Members" not in result

    def test_empty_transcript_under_budget(self):
        app = _make_kb(
            "overview",
            [("a.md", "section a"), ("b.md", "section b")],
        )
        result = select_content(app, "", budget_chars=60_000)
        assert "overview" in result
        assert "section a" in result
        assert "section b" in result

    def test_empty_transcript_over_budget(self):
        app = _make_kb(
            "O" * 100,
            [("a.md", "A" * 50_000), ("b.md", "B" * 50_000)],
        )
        # total sections = 100000 > budget - overview = 59900
        result = select_content(app, "", budget_chars=60_000)
        assert "O" * 100 in result
        assert "A" * 50_000 not in result
        assert "B" * 50_000 not in result

    def test_overview_only_no_sections(self):
        app = _make_kb("just an overview")
        result = select_content(app, "anything")
        assert result == "just an overview"

    def test_overview_exceeds_budget_still_included(self):
        big_overview = "X" * 100_000
        app = _make_kb(big_overview)
        result = select_content(app, "anything", budget_chars=50_000)
        assert big_overview in result

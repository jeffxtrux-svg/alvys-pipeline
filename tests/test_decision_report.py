"""Tests for the weekly Risk & Decisions report (src/decision_report.py).

Pure rendering — no network. Covers the markdown->HTML subset converter, the
Claude starter-link encoding, and that the assembled report carries both
knowledge-base sections plus the discuss-with-Claude affordances.

Run directly:  python tests/test_decision_report.py
Or via pytest: pytest tests/test_decision_report.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.decision_report import (  # noqa: E402
    _md_to_html, _inline, _claude_link, build_decision_report, _STATIC_PROMPTS)


def test_md_strips_frontmatter_and_renders_table_bold_wikilinks():
    md = (
        "---\n"
        "title: X\n"
        "type: register\n"
        "---\n"
        "# Heading\n"
        "Intro **bold** and [[Risk Register]] link.\n"
        "| A | B |\n"
        "|---|---|\n"
        "| 1 | 2 |\n"
    )
    html = _md_to_html(md)
    assert "title: X" not in html and "type: register" not in html   # frontmatter stripped
    assert "<h1" in html and "Heading" in html
    assert "<strong>bold</strong>" in html
    assert "Risk Register" in html and "[[" not in html              # wikilink -> plain text
    assert "<table" in html and "<td" in html and ">1<" in html      # table rendered


def test_md_renders_blockquote_and_list():
    html = _md_to_html("> a note\n\n- item one\n- item two\n")
    assert "border-left" in html and "a note" in html               # blockquote callout
    assert "<ul" in html and "<li" in html and "item two" in html


def test_inline_real_links_and_italics():
    assert "<a href='https://x.com'" in _inline("[x](https://x.com)")
    assert "<em" in _inline("status _pending_ here")


def test_claude_link_encodes_prompt():
    url = _claude_link("top risks this week?")
    assert url.startswith("https://claude.ai/new?q=")
    assert " " not in url                                            # whitespace encoded


def test_build_report_has_both_sections_and_claude():
    html = build_decision_report(
        "Monday, June 15, 2026",
        "# Risk Register\n\nrisk body.",
        "# Decision Journal\n\ndecision body.")
    assert "Risk &amp; Decisions Report" in html                     # branded header
    assert "Risk Register" in html and "Decision Journal" in html    # both KB sections
    assert "claude.ai/new" in html                                   # discuss-with-Claude links
    assert "Monday, June 15, 2026" in html
    # All starter prompts are present for copy-paste fallback.
    for _label, prompt in _STATIC_PROMPTS:
        assert prompt in html


def test_build_report_handles_missing_pages():
    html = build_decision_report("Monday, June 15, 2026", "", "")
    assert "Risk register not found" in html and "Decision journal not found" in html


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

"""Regression tests for the Karpathy-Wiki archive helper.

Pins:
  - save() writes <root>/<source>/<timestamp>-<slug>.md and returns the path
  - save() is a no-op (returns "") when the root directory doesn't exist,
    so local pipeline runs without the wiki on disk don't crash
  - slug sanitization (special characters collapsed to hyphens)
  - frontmatter contains the keys the wiki librarian expects

Run:  pytest tests/test_karpathy_writer.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.karpathy_writer import frontmatter, save, _slug  # noqa: E402


def test_save_writes_file_and_returns_path():
    with tempfile.TemporaryDirectory() as root:
        path = save("scorecard", "executive-brief", "# Hi\n", root=root)
        assert path
        p = Path(path)
        assert p.exists()
        assert p.parent.name == "scorecard"
        assert p.suffix == ".md"
        assert p.read_text() == "# Hi\n"


def test_save_creates_source_subdirectory():
    with tempfile.TemporaryDirectory() as root:
        save("new-source", "first-run", "body", root=root)
        assert (Path(root) / "new-source").is_dir()


def test_save_filename_has_timestamp():
    with tempfile.TemporaryDirectory() as root:
        path = save("samsara-alerts", "fleet-alert", "body", root=root)
        name = Path(path).name
        # YYYY-MM-DDTHH-MM-<slug>.md  -> first 16 chars are the timestamp
        assert name[:4].isdigit()           # year
        assert name[4] == "-"
        assert "T" in name[:16]
        assert name.endswith("-fleet-alert.md")


def test_save_is_noop_when_root_missing():
    """If Karpathy-Wiki/raw/ isn't on disk (local dev), save() must NOT crash —
    it returns '' so the surrounding pipeline run keeps going."""
    missing = "/tmp/definitely-does-not-exist-zzz-12345"
    if os.path.exists(missing):
        # extremely unlikely but be safe
        os.rmdir(missing)
    path = save("alvys", "summary", "body", root=missing)
    assert path == ""


def test_save_honors_KARPATHY_WIKI_ROOT_env(monkeypatch=None):
    """Env override beats the explicit root arg — lets the workflow pin a
    location without editing every call site."""
    # crude monkeypatch without pytest fixture
    import os as _os
    with tempfile.TemporaryDirectory() as override_root:
        old = _os.environ.get("KARPATHY_WIKI_ROOT")
        _os.environ["KARPATHY_WIKI_ROOT"] = override_root
        try:
            path = save("alvys", "run", "x", root="/nope/missing")
            assert path
            assert override_root in path
        finally:
            if old is None:
                _os.environ.pop("KARPATHY_WIKI_ROOT", None)
            else:
                _os.environ["KARPATHY_WIKI_ROOT"] = old


def test_slug_sanitizes_special_chars():
    assert _slug("Hello, World!") == "hello-world"
    assert _slug("X-Trux Inc.") == "x-trux-inc"
    assert _slug("nothing\\to///clean") == "nothing-to-clean"


def test_slug_collapses_runs_and_trims_edges():
    assert _slug("  --foo  bar--  ") == "foo-bar"


def test_slug_empty_becomes_untitled():
    assert _slug("") == "untitled"
    assert _slug("!!!") == "untitled"


def test_frontmatter_contains_required_keys():
    fm = frontmatter("My Title", "scorecard", run="42")
    assert fm.startswith("---\n")
    assert fm.rstrip().endswith("---")
    assert "title: My Title" in fm
    assert "source: scorecard" in fm
    assert "captured: " in fm
    assert "kind: pipeline-archive" in fm
    assert "run: 42" in fm                    # passthrough extras work


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))

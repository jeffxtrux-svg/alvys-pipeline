"""Regression tests for the Karpathy-Wiki auto-compiler's safety pieces.

These pin the in-code guardrails so a future change can't accidentally let
the librarian write outside /wiki or trip on common JSON-response shapes:

  - _validate_path: refuses paths outside Karpathy-Wiki/wiki/, with traversal,
    or that aren't markdown.
  - _extract_json: handles fenced blocks, bare objects, and trailing text.
  - _apply_changes: writes only into a sandbox /wiki, never into /raw.

Run:  pytest tests/test_karpathy_compiler.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.karpathy_compiler import (  # noqa: E402
    _apply_changes,
    _extract_json,
    _validate_path,
)


def test_validate_path_accepts_canonical_wiki_path():
    assert _validate_path("Karpathy-Wiki/wiki/scaling-laws.md") == Path(
        "Karpathy-Wiki/wiki/scaling-laws.md")


def test_validate_path_rejects_paths_outside_wiki():
    assert _validate_path("Karpathy-Wiki/raw/foo.md") is None
    assert _validate_path("src/scorecard_email.py") is None
    assert _validate_path("/etc/passwd") is None


def test_validate_path_rejects_traversal():
    assert _validate_path("Karpathy-Wiki/wiki/../raw/x.md") is None


def test_validate_path_rejects_non_markdown():
    assert _validate_path("Karpathy-Wiki/wiki/note.txt") is None
    assert _validate_path("Karpathy-Wiki/wiki/data.json") is None


def test_extract_json_handles_fenced_block():
    text = """Sure, here is the result:

```json
{"updates": [], "index_content": "# index", "notes": "ok"}
```

That's it."""
    payload = _extract_json(text)
    assert payload is not None
    assert payload["updates"] == []
    assert payload["index_content"] == "# index"


def test_extract_json_handles_bare_object():
    payload = _extract_json('{"updates": [{"path": "Karpathy-Wiki/wiki/a.md", "content": "X"}]}')
    assert payload is not None
    assert payload["updates"][0]["path"] == "Karpathy-Wiki/wiki/a.md"


def test_extract_json_returns_none_on_garbage():
    assert _extract_json("Hello there") is None
    assert _extract_json("{ unterminated") is None


def test_apply_changes_writes_only_to_wiki(monkeypatch=None):
    """Run _apply_changes against a sandbox /wiki and prove that out-of-tree
    paths are silently rejected, while in-tree ones are written."""
    import src.karpathy_compiler as kc
    with tempfile.TemporaryDirectory() as root:
        wiki = Path(root) / "Karpathy-Wiki" / "wiki"
        wiki.mkdir(parents=True)
        # Patch the module constant for this test
        old_root = kc.WIKI_DIR
        kc.WIKI_DIR = wiki
        # Change CWD so relative paths in _validate_path resolve correctly
        old_cwd = os.getcwd()
        os.chdir(root)
        try:
            payload = {
                "updates": [
                    {"path": "Karpathy-Wiki/wiki/scaling-laws.md", "content": "# Scaling Laws\n"},
                    {"path": "Karpathy-Wiki/raw/should-skip.md", "content": "bad"},
                    {"path": "src/scorecard_email.py", "content": "evil = True"},
                ],
                "index_content": "# Index\n\n- [[Scaling Laws]]\n",
            }
            count, applied = _apply_changes(payload)
        finally:
            kc.WIKI_DIR = old_root
            os.chdir(old_cwd)
        # Two writes: the in-wiki page + index. The /raw and src/ entries dropped.
        assert count == 2
        assert any("scaling-laws.md" in p for p in applied)
        assert any("index.md" in p for p in applied)
        assert not any("scorecard_email.py" in p for p in applied)
        assert not any("/raw/" in p or "raw/should-skip" in p for p in applied)
        assert (wiki / "scaling-laws.md").read_text() == "# Scaling Laws\n"
        assert (wiki / "index.md").exists()


def test_apply_changes_skips_when_no_index_content():
    """A run that has no updates and no index returns 0 — workflow then skips the commit."""
    count, applied = _apply_changes({"updates": [], "index_content": ""})
    assert count == 0
    assert applied == []


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))

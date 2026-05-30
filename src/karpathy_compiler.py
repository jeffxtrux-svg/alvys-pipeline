"""Karpathy-Wiki auto-compiler.

Runs Claude against the wiki's librarian instructions + the /raw inbox + the
current /wiki state, parses the structured response, and applies the file
changes. Intended to run from a scheduled GitHub Action so /wiki always
reflects the latest /raw inputs.

Hard guardrails (enforced in code, not just prompt):
  - Never writes to /raw.
  - Every output path must be under /wiki/.
  - Skips the commit if the model returns malformed output.

What gets sent to Claude:
  1. The librarian rules from Karpathy-Wiki/CLAUDE.md (system prompt).
  2. The current /wiki state (all existing pages so the librarian doesn't
     duplicate work).
  3. The trailing 30 days of /raw inputs (cap on context size — older /raw
     is already represented in the existing /wiki pages).

Required env vars:
  ANTHROPIC_API_KEY  — used by the anthropic SDK
  KARPATHY_MODEL     — optional override of the Claude model name.

Optional knobs:
  KARPATHY_RAW_DAYS  — how many days of /raw to include (default 30).
  KARPATHY_MAX_FILES — total raw-file budget to avoid runaway context
                        (default 60).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

import anthropic

log = logging.getLogger("karpathy_compiler")

WIKI_ROOT = Path("Karpathy-Wiki")
RAW_DIR = WIKI_ROOT / "raw"
WIKI_DIR = WIKI_ROOT / "wiki"
RULES_PATH = WIKI_ROOT / "CLAUDE.md"

DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_RAW_DAYS = 30
DEFAULT_MAX_FILES = 60
MAX_OUTPUT_TOKENS = 16_000


def _load_rules() -> str:
    if not RULES_PATH.exists():
        sys.exit(f"ERROR: {RULES_PATH} missing — can't run without librarian rules")
    return RULES_PATH.read_text(encoding="utf-8")


def _list_raw_recent(days: int, max_files: int) -> list[Path]:
    """Most recently modified /raw files, capped by count and age."""
    if not RAW_DIR.exists():
        return []
    cutoff = __import__("time").time() - days * 86400
    files = []
    for p in RAW_DIR.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        try:
            if p.stat().st_mtime >= cutoff:
                files.append(p)
        except OSError:
            continue
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return files[:max_files]


def _list_existing_wiki() -> list[Path]:
    if not WIKI_DIR.exists():
        return []
    return sorted([p for p in WIKI_DIR.rglob("*.md") if p.is_file()])


def _read_files_block(files: list[Path], root: Path, header: str) -> str:
    """Render a set of files as a single text block tagged with paths."""
    if not files:
        return f"# {header}\n\n(none)\n"
    parts = [f"# {header}\n"]
    for p in files:
        rel = p.relative_to(root.parent)
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            content = f"(could not read: {exc})"
        parts.append(f"## File: `{rel}`\n\n```\n{content}\n```\n")
    return "\n".join(parts)


def _build_user_message() -> str:
    raw_days = int(os.environ.get("KARPATHY_RAW_DAYS", DEFAULT_RAW_DAYS))
    max_files = int(os.environ.get("KARPATHY_MAX_FILES", DEFAULT_MAX_FILES))
    raw_files = _list_raw_recent(raw_days, max_files)
    wiki_files = _list_existing_wiki()
    log.info("Compiling: %d recent raw files (<= %d days), %d existing wiki pages",
             len(raw_files), raw_days, len(wiki_files))

    raw_block = _read_files_block(raw_files, RAW_DIR, f"INBOX (`/raw`, last {raw_days} days)")
    wiki_block = _read_files_block(wiki_files, WIKI_DIR, "CURRENT WIKI (`/wiki`)")

    instructions = (
        "Compile the inbox into the wiki following the librarian rules in your "
        "system prompt. Then return a SINGLE JSON object (and nothing else outside "
        "the JSON) with the following shape:\n\n"
        "```\n"
        "{\n"
        "  \"updates\": [\n"
        "    {\"path\": \"Karpathy-Wiki/wiki/<name>.md\", \"content\": \"...\"},\n"
        "    ...\n"
        "  ],\n"
        "  \"index_content\": \"...complete contents of /wiki/index.md...\",\n"
        "  \"notes\": \"one-paragraph human-readable summary of what changed\"\n"
        "}\n"
        "```\n\n"
        "Rules for the response:\n"
        "- Every `path` MUST start with `Karpathy-Wiki/wiki/` (no writes outside /wiki).\n"
        "- Provide the FULL final content of each file you update (not a diff).\n"
        "- Only include pages you actually want to create or modify; omit unchanged pages.\n"
        "- `index_content` is the complete intended /wiki/index.md after this run.\n"
        "- Do not write to /raw. Do not include any file paths outside Karpathy-Wiki/wiki/.\n"
        "- If there's nothing new to compile, return `\"updates\": []` and the current\n"
        "  index content unchanged.\n"
    )
    return f"{wiki_block}\n\n{raw_block}\n\n{instructions}"


def _extract_json(text: str) -> dict | None:
    """Pull the first top-level JSON object out of Claude's response."""
    text = text.strip()
    # Strip ```json ... ``` fences if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    # Otherwise find the first { ... matching } pair
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError as exc:
                    log.warning("JSON parse failed: %s", exc)
                    return None
    return None


def _validate_path(path: str) -> Path | None:
    """Refuse paths outside Karpathy-Wiki/wiki/ or with path traversal."""
    if not path.startswith("Karpathy-Wiki/wiki/"):
        log.warning("Rejecting out-of-tree path: %r", path)
        return None
    if ".." in Path(path).parts:
        log.warning("Rejecting path with .. traversal: %r", path)
        return None
    if not path.endswith(".md"):
        log.warning("Rejecting non-markdown path: %r", path)
        return None
    return Path(path)


def _apply_changes(payload: dict) -> tuple[int, list[str]]:
    """Write the model's proposed updates. Return (count, applied_paths)."""
    applied: list[str] = []
    for entry in payload.get("updates", []) or []:
        path = entry.get("path", "")
        content = entry.get("content", "")
        if not isinstance(path, str) or not isinstance(content, str):
            continue
        target = _validate_path(path)
        if target is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        applied.append(str(target))
    index = payload.get("index_content")
    if isinstance(index, str) and index.strip():
        idx_path = WIKI_DIR / "index.md"
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        idx_path.write_text(index, encoding="utf-8")
        applied.append(str(idx_path))
    return len(applied), applied


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ERROR: ANTHROPIC_API_KEY not set")

    model = os.environ.get("KARPATHY_MODEL", DEFAULT_MODEL)
    rules = _load_rules()
    user_msg = _build_user_message()

    log.info("Calling %s (rules=%d chars, user=%d chars)", model, len(rules), len(user_msg))
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=rules,
        messages=[{"role": "user", "content": user_msg}],
    )

    # response.content is a list of content blocks
    text = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text")
    log.info("Response: %d chars (input %d tokens, output %d tokens)",
             len(text),
             getattr(response.usage, "input_tokens", -1),
             getattr(response.usage, "output_tokens", -1))

    payload = _extract_json(text)
    if payload is None:
        log.error("Could not parse JSON from response — skipping compile.\n%s", text[:1000])
        return 1

    count, applied = _apply_changes(payload)
    notes = (payload.get("notes") or "").strip()
    if not count:
        log.info("Compiler returned no file changes. Notes: %s", notes or "(none)")
        return 0
    log.info("Applied %d file change(s):\n  %s", count, "\n  ".join(applied))
    if notes:
        log.info("Compiler notes: %s", notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Shared helper: write pipeline output into Karpathy-Wiki/raw/.

Each pipeline run drops a markdown file into Karpathy-Wiki/raw/<source>/. The
wiki librarian (see Karpathy-Wiki/CLAUDE.md) reads /raw and compiles /wiki
pages from it — we don't touch /wiki here.

Safe no-op when the wiki folder isn't checked out (e.g. local dev runs without
the wiki on disk).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import pandas as pd

log = logging.getLogger("karpathy_writer")

DEFAULT_ROOT = "Karpathy-Wiki/raw"


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", str(s).lower()).strip("-")
    return s or "untitled"


def save(source: str, slug: str, content_md: str, root: str | None = None) -> str:
    """Write content_md to <root>/<source>/<timestamp>-<slug>.md and return the path.

    Returns "" (and logs a warning) if the root directory doesn't exist —
    pipeline runs without the wiki on disk shouldn't crash, the archive is
    best-effort.
    """
    base = Path(os.environ.get("KARPATHY_WIKI_ROOT", root or DEFAULT_ROOT))
    if not base.exists():
        log.info("Karpathy-Wiki root %s missing; skipping archive of %s/%s",
                 base, source, slug)
        return ""
    folder = base / _slug(source)
    folder.mkdir(parents=True, exist_ok=True)
    ts = pd.Timestamp.now(tz="America/Chicago").strftime("%Y-%m-%dT%H-%M")
    path = folder / f"{ts}-{_slug(slug)}.md"
    path.write_text(content_md, encoding="utf-8")
    log.info("Archived to %s (%d chars)", path, len(content_md))
    return str(path)


def frontmatter(title: str, source: str, **extra) -> str:
    """Standard YAML frontmatter the wiki librarian expects on each /raw page."""
    ts = pd.Timestamp.now(tz="America/Chicago").strftime("%Y-%m-%d %H:%M %Z")
    lines = ["---",
             f"title: {title}",
             f"source: {source}",
             f"captured: {ts}",
             "kind: pipeline-archive"]
    for k, v in extra.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"

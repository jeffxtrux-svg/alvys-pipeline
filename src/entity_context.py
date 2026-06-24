"""Entity context lookup — Phase 2E (entity-level pattern pages → brief).

Given a list of driver / customer names appearing in today's brief data,
return any matching `Karpathy-Wiki/wiki/{drivers,customers}/<slug>.md`
pages so the brief can surface "what we already know about this person /
account" inline.

v1 scope: lookup + extract first paragraph after `## At a glance` (or the
page summary if there's no At a glance heading). No fuzzy matching beyond
case + whitespace normalization — names must match the file slug. v2 will
add Levenshtein matching and auto-injection into specific brief sections.

Fail-soft: missing directory, malformed page, no matches — return {} and
the brief silently omits any entity-context strip.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger("entity_context")

_ROOT = Path(__file__).resolve().parent.parent / "Karpathy-Wiki" / "wiki"
_DRIVERS_DIR = _ROOT / "drivers"
_CUSTOMERS_DIR = _ROOT / "customers"


def _slug(name: str) -> str:
    """Normalize a name into the kebab-case slug used in filenames.
    'MICHAEL HALL' → 'michael-hall', 'JJ Hupf' → 'jj-hupf'."""
    if not name:
        return ""
    s = name.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    return s


def _find_page(slug: str) -> Path | None:
    """Look for `<slug>.md` under drivers/, then customers/, then the wiki
    root (for legacy flat customer pages like billion-auto.md)."""
    if not slug:
        return None
    for directory in (_DRIVERS_DIR, _CUSTOMERS_DIR, _ROOT):
        candidate = directory / f"{slug}.md"
        if candidate.exists():
            return candidate
    return None


def _extract_summary(page_text: str, max_chars: int = 320) -> str:
    """Pull the first useful prose chunk from a wiki page.

    Strategy:
      1. Strip YAML frontmatter (everything between leading --- ... ---)
      2. Skip the H1
      3. Take the first non-empty paragraph (single line of text, not a
         heading / list / table)
      4. Truncate to max_chars with ellipsis

    Falls back to "" if no usable paragraph is found.
    """
    if not page_text:
        return ""
    # Strip frontmatter
    if page_text.startswith("---"):
        end = page_text.find("\n---", 3)
        if end != -1:
            page_text = page_text[end + 4:]
    # Split into lines, skip h1 + blank
    lines = page_text.splitlines()
    in_para = False
    para_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_para and para_lines:
                break
            continue
        # Skip headings and list/table markers
        if stripped.startswith(("#", "-", "*", "|", ">")):
            if in_para:
                break
            continue
        in_para = True
        para_lines.append(stripped)
        if sum(len(l) + 1 for l in para_lines) > max_chars:
            break
    summary = " ".join(para_lines).strip()
    if len(summary) > max_chars:
        summary = summary[:max_chars - 1].rstrip() + "…"
    return summary


def lookup(names: list[str]) -> dict[str, dict]:
    """For each name in `names`, return its slug + page path + summary if
    a matching page exists. Returns {} when nothing matches.

    Output shape: { display_name: {"slug": ..., "path": str, "summary": ...} }
    """
    if not names:
        return {}
    out: dict[str, dict] = {}
    seen: set[str] = set()
    for name in names:
        slug = _slug(name)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        page = _find_page(slug)
        if not page:
            continue
        try:
            text = page.read_text(encoding="utf-8")
        except Exception as exc:
            log.warning("entity_context: failed to read %s (%s)", page, exc)
            continue
        out[name] = {
            "slug": slug,
            "path": str(page.relative_to(_ROOT.parent)),  # Karpathy-Wiki/wiki/...
            "summary": _extract_summary(text),
        }
    return out


def list_available(directory: str = "drivers") -> list[str]:
    """List all slugs under drivers/ or customers/. Skips _README and _template."""
    dir_path = _ROOT / directory
    if not dir_path.exists():
        return []
    return sorted(
        p.stem for p in dir_path.glob("*.md")
        if not p.stem.startswith("_")
    )


def render_strip_html(matches: dict[str, dict],
                       *,
                       title: str = "What we know · entities on today's brief",
                       ink: str = "#1a1a1a",
                       mute: str = "#6b6b6b",
                       line: str = "#ececec",
                       accent: str = "#1a3a6b",
                       max_items: int = 4) -> str:
    """Render a compact strip listing entity-context matches. Hidden when
    `matches` is empty (no pages exist for any of today's named entities)."""
    if not matches:
        return ""
    items_html = ""
    for name, info in list(matches.items())[:max_items]:
        summary = info.get("summary") or ""
        if not summary:
            continue
        items_html += (
            f"<li style='margin-bottom:8px;'>"
            f"<span style='font-weight:700;color:{accent};font-size:12px;'>"
            f"{name}</span> "
            f"<span style='color:{mute};font-size:10px;'>· {info['path']}</span>"
            f"<div style='color:{ink};font-size:11.5px;margin-top:2px;'>"
            f"{summary}</div>"
            f"</li>"
        )
    if not items_html:
        return ""
    return (
        f"<div style='margin:0 0 14px;padding:10px 14px;background:#fcfcfc;"
        f"border:1px solid {line};border-radius:6px;'>"
        f"<div style='font-size:10px;font-weight:700;letter-spacing:1.5px;"
        f"color:{mute};text-transform:uppercase;margin-bottom:8px;'>"
        f"{title}</div>"
        f"<ul style='margin:0;padding-left:18px;'>{items_html}</ul>"
        f"</div>"
    )

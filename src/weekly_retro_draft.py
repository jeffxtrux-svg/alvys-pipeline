"""Weekly retro draft generator — Phase 2D supporting automation.

Builds a draft retro YAML block prepopulated with this week's git activity
and writes it to `Karpathy-Wiki/wiki/weekly-retros.yml` as a NEW entry at
the top of the `retros:` list. The Friday workflow runs this, commits the
draft to a branch, and opens a PR for human review — the goal is to lower
the friction of the "10-min Friday retro" habit from "open file, remember
schema, write prose" to "open PR, fill in the blanks, merge."

The pre-population is intentionally light:
  - week_of: the Monday of the current week
  - captured: today
  - captured_by: "DRAFT" (forces a human edit before merge)
  - surprised_by / worked / didnt_work: empty (humans must fill)
  - lessons: empty
  - tested_predictions: empty
  - Comment block above the entry listing this week's commits + any
    decisions/forecasts whose grade flipped, so the human has the raw
    material in front of them while writing.

Re-running on the same week is safe: if a block already exists with the
same week_of, this script appends a "RE-DRAFT" comment and does not
duplicate.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger("weekly_retro_draft")

_RETROS_PATH = (Path(__file__).resolve().parent.parent
                / "Karpathy-Wiki" / "wiki" / "weekly-retros.yml")


def _monday_of_this_week(today: date | None = None) -> date:
    today = today or date.today()
    return today - timedelta(days=today.weekday())


def _git_log_this_week(since: date) -> list[str]:
    """Return one-line commit summaries since the given date. Best-effort —
    falls back to empty list if git isn't available."""
    try:
        out = subprocess.check_output(
            ["git", "log", "--since", since.isoformat(),
             "--pretty=format:- %s", "--no-merges"],
            cwd=Path(__file__).resolve().parent.parent,
            text=True, timeout=30,
        )
        return [line for line in out.strip().splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.warning("git log this-week failed: %s", e)
        return []


def _week_has_block(content: str, week_of: str) -> bool:
    """Cheap text check — is a block with this week_of already in the file?"""
    return f'week_of: "{week_of}"' in content


def build_draft_block(today: date | None = None,
                       captured_by: str = "DRAFT — replace before merge") -> str:
    """Return the YAML block text + a leading comment listing this week's
    raw material. Not yet inserted; caller writes it into the file."""
    today = today or date.today()
    monday = _monday_of_this_week(today)
    commits = _git_log_this_week(monday)

    # Comment block listing this week's commits so the human has source
    # material visible while filling in the prose fields. Capped so the
    # file doesn't bloat — a heavy commit week can have 50+ lines.
    if commits:
        commit_lines = "\n".join(
            f"  #   {c.lstrip('- ').strip()}" for c in commits[:25]
        )
        if len(commits) > 25:
            commit_lines += f"\n  #   ... and {len(commits) - 25} more this week"
        comment_block = (
            f"  # ----- DRAFT for week of {monday.isoformat()} (auto-generated) -----\n"
            f"  # Fill in surprised_by / worked / didnt_work / lessons below,\n"
            f"  # set captured_by to your name, then merge. The git activity\n"
            f"  # below is just source material to jog your memory — delete\n"
            f"  # these comment lines after merge if you want, the librarian\n"
            f"  # doesn't care.\n"
            f"  #\n"
            f"  # This week's commits ({len(commits)} total):\n"
            f"{commit_lines}\n"
            f"  # ---------------------------------------------------------------\n"
        )
    else:
        comment_block = (
            f"  # ----- DRAFT for week of {monday.isoformat()} (auto-generated) -----\n"
            f"  # No git commits found this week (clean slate or git unavailable).\n"
            f"  # Fill in the fields below and merge.\n"
            f"  # ---------------------------------------------------------------\n"
        )

    block = (
        f"{comment_block}"
        f'  - week_of: "{monday.isoformat()}"\n'
        f'    captured: "{today.isoformat()}"\n'
        f'    captured_by: "{captured_by}"\n'
        f'    surprised_by: |\n'
        f"      \n"
        f'    worked: |\n'
        f"      \n"
        f'    didnt_work: |\n'
        f"      \n"
        f"    lessons:\n"
        f"      # - \"If X then Y.\"\n"
        f"    tested_predictions: []\n"
    )
    return block


def insert_draft(path: Path | None = None, today: date | None = None) -> bool:
    """Insert the draft at the top of the `retros:` list. Returns True
    if a new block was added, False if this week already has a block."""
    p = path or _RETROS_PATH
    today = today or date.today()
    monday = _monday_of_this_week(today)

    if not p.exists():
        log.error("retros file not found at %s", p)
        return False

    content = p.read_text()
    if _week_has_block(content, monday.isoformat()):
        log.info("week_of %s already has a block — skipping draft insert",
                 monday.isoformat())
        return False

    # Find the `retros:` key and insert the new block immediately after it
    # (top of the list, so the newest week is always first). If the key isn't
    # found, error out — file is malformed.
    lines = content.splitlines(keepends=True)
    insert_idx = None
    for i, line in enumerate(lines):
        if line.rstrip() == "retros:":
            insert_idx = i + 1
            break
    if insert_idx is None:
        log.error("retros file at %s has no `retros:` top-level key", p)
        return False

    draft = build_draft_block(today=today)
    # Insert + blank line after for readability
    new_content = "".join(lines[:insert_idx]) + draft + "\n" + "".join(lines[insert_idx:])
    p.write_text(new_content)
    log.info("Inserted draft for week of %s into %s", monday.isoformat(), p)
    return True


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                         datefmt="%H:%M:%S")
    inserted = insert_draft()
    if inserted:
        print("DRAFT_INSERTED=1")
        return 0
    print("DRAFT_INSERTED=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())

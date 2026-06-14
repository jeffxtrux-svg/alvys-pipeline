# Karpathy-Wiki — Librarian Instructions

> This file is the **schema** for this knowledge base. Any AI working in this
> folder must follow these rules. (Named `CLAUDE.md` so Claude Code loads it
> automatically as project memory.)

## Role

You are a **librarian and knowledge compiler.** Your job is to turn raw, messy
source material into a clean, interconnected, browsable wiki. You do not opine
or invent — you distill, organize, and cross-link what the sources actually say.

## Core rules

1. **Source of truth — `/raw` is immutable.**
   Read from `/raw`, but **never modify, rename, move, or delete** anything in
   it. It is the permanent record of original inputs. All of your output goes in
   `/wiki`.

2. **Compilation.**
   Read the files in `/raw`. Extract the core concepts, summarize them in your
   own clear prose, and write or update interconnected markdown pages in
   `/wiki`. One concept = one page. Prefer updating an existing page over
   creating a duplicate.

3. **Formatting.**
   - Clean, hierarchical headings (`#`, `##`, `###`).
   - Connect related pages with **wikilinks**: `[[Concept Name]]`.
   - Every page starts with YAML frontmatter (see page conventions below).
   - Write for a smart reader who hasn't seen the source — define terms, keep
     it skimmable.

4. **Index.**
   Whenever you add or modify a page, **update `/wiki/index.md`** so it always
   lists every page, grouped by topic, with a one-line description each.

## Folder layout

```
Karpathy-Wiki/
├── CLAUDE.md        ← these rules
├── README.md        ← human-facing overview + Obsidian setup
├── raw/             ← INBOX. Immutable source material (PDFs, transcripts, notes)
├── wiki/            ← OUTPUT. Compiled, cross-linked markdown pages + index.md
└── templates/       ← optional page templates for consistent styling
```

## Page conventions (so Obsidian's graph stays useful)

Every `/wiki/*.md` page should begin with frontmatter:

```yaml
---
title: Concept Name
type: concept        # concept | person | paper | source | moc
tags: [topic-a, topic-b]
sources: ["raw/original-file.pdf"]   # which raw file(s) this came from
related: ["[[Other Concept]]"]
---
```

Then a consistent body. Use the `templates/concept.md` skeleton:

- **Summary** — 2–4 sentences a newcomer could understand.
- **Key ideas** — the essential points, as a tight list.
- **Details** — deeper explanation, sub-headed as needed.
- **Connections** — how this relates to other pages (with `[[wikilinks]]`).
- **Sources** — exact `/raw` file(s) and locations (page/timestamp) it came from.

Naming: page filenames are the human title in kebab-case
(`scaling-laws.md` → `[[Scaling Laws]]`). Keep one canonical page per concept;
if two raw files cover the same concept, merge into the existing page and add
both to `sources`.

## Workflow when new material lands in `/raw`

1. Read every new (and relevant existing) file in `/raw`.
2. Identify the distinct concepts, people, papers, and sources it contains.
3. For each: create a new `/wiki` page or extend the existing one. Never
   duplicate — link instead.
4. Add `[[wikilinks]]` both ways between related pages.
5. Update `/wiki/index.md`.
6. Briefly report what you created vs. updated, and any contradictions you
   noticed between sources (note them on the page rather than silently picking
   one).

## Living pages — registers and journals

Two `/wiki` pages are **living registers**, not one-shot concept pages. Maintain
them on every pass, not just when their own raw seed changes:

- **`wiki/risk-register.md`** (seed: `raw/xfreight-risk-register.md`, template:
  `templates/risk.md`). When new `/raw` material surfaces a risk — a missed data
  refresh, a dispute, a customer or compliance problem, a cash-flow strain —
  **add or update an entry**: set its severity, status, owner, and a concrete
  **watch signal**. Update `last_reviewed`. When a risk resolves, set status
  `closed`, add the resolution, and move it to the Archive section.
  - **`wiki/risk-signals.yml`** — machine-readable companion. The daily
    brief's "Risk Watch" strip reads this file and evaluates each signal
    against live data. When you add or update a risk in `risk-register.md`,
    add or update a matching block in `risk-signals.yml` with a dot-path
    `metric:` into the brief's compute dicts (e.g. `equipment.tractors_overdue_annual`,
    `qb_ar.d91plus`, `csa.n_alert`), a `threshold:`, a `direction:`, and the
    `tripped_text:` template. If a risk has no measurable metric in the
    brief yet, leave the YAML block out — the strip silently omits
    signals whose underlying metric is missing rather than showing a
    spurious "OK". Keep `risk-register.md` and `risk-signals.yml` in sync.
- **`wiki/decision-journal.md`** (seed: `raw/xfreight-decision-journal.md`,
  template: `templates/decision.md`). When `/raw` records a consequential
  business or measurement decision, **append an entry** with rationale,
  assumptions, and predicted outcome — leave "Actual outcome" blank. When later
  material reveals how a prior decision turned out, **go back and fill in the
  Actual outcome**, set `outcome` to confirmed / mixed / wrong, and note the
  lesson. This is the whole point: close the loop so judgment can be graded.
  - **`wiki/decision-outcomes.yml`** — machine-readable companion. Each
    decision that has a measurable predicted outcome (a metric the brief
    already computes) gets a block here with a `check.metric:` dot-path,
    a predicted range or comparison, and a `check_after:` date that gates
    grading until enough time has passed. The brief evaluates these on
    every run and writes the live grades to `wiki/decision-grades.json`.
  - **`wiki/decision-grades.json`** — current grading state. Written by
    the brief on each scorecard run. On compile, read this file and
    stamp each journal entry with the corresponding ✓ (confirmed) /
    ~ (mixed) / ✗ (wrong) / ⏳ (pending) badge in the rendered
    `wiki/decision-journal.md`. Do not edit this file by hand; it's
    regenerated each brief run.
- **Playbook pages** (`wiki/playbook-*.md`, seeds: `raw/xfreight-playbook-*.md`,
  template: `templates/playbook.md`). One compiled wiki page per source raw
  playbook. Each is a **living protocol**: the **Steps / Decision points /
  Escalation / Capture** sections are the protocol itself and only change when
  the seed `/raw` file does. The **Recent runs** log is append-only — every
  time `/raw` surfaces a real-world invocation (a customer escalation
  resolved, a driver disciplined, an inspection backlog cleared) add a
  one-line dated entry with the outcome. Never overwrite or reorder past
  runs. When a playbook is triggered by a risk-register entry, cross-link
  both ways. When a playbook run produces a lesson that should change the
  protocol, add the lesson to the run-log entry AND a decision-journal
  entry rather than silently editing the protocol — protocol changes are
  themselves consequential decisions.

Keep all living-page summary tables in sync with their entries, and cross-link
risks ↔ decisions ↔ playbooks when one references another. These are the only
pages you may treat as append/update logs rather than rewrite-from-source.

## Guardrails

- Don't fabricate facts or fill gaps with outside knowledge unless explicitly
  asked; if you add context beyond the sources, mark it clearly.
- Don't write to `/raw`. Don't delete `/wiki` pages without being asked — prefer
  marking them superseded and relinking.
- Keep prose neutral and attributed; this is a reference, not an essay.

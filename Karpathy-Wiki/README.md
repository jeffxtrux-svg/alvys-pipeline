# Karpathy-Wiki

A **self-evolving personal knowledge base.** You dump raw source material into
`/raw`; Claude acts as a librarian and compiles it into a clean, cross-linked
markdown wiki in `/wiki`. Point Obsidian at the folder and your notes become an
interactive graph of connected ideas.

```
        you add files                Claude compiles            you browse
   ┌──────────────────┐   ┌───────────────────────────┐   ┌──────────────────┐
   │  /raw  (inbox,    │──▶│  /wiki  (compiled, linked  │──▶│  Obsidian graph  │
   │  immutable)       │   │  markdown + index.md)      │   │  view            │
   └──────────────────┘   └───────────────────────────┘   └──────────────────┘
            ▲                          │
            └──── rules in CLAUDE.md ──┘
```

## Folder structure

| Folder | Purpose |
|--------|---------|
| `raw/` | **Inbox.** Raw, unmodified sources (PDFs, transcripts, articles, notes). Immutable — Claude never edits it. |
| `wiki/` | **Knowledge base.** Where Claude writes, updates, and cross-links compiled markdown pages. Contains `index.md`. |
| `templates/` | Optional page skeletons (`concept`, `person`, `source`) for consistent styling. |
| `CLAUDE.md` | The librarian "schema" — the rules Claude follows. |

## How to use it

### 1. Add material
Drop one or more source files into [`raw/`](raw/). Descriptive filenames help —
pages cite their origin by filename.

### 2. Ask Claude to compile (Step 3)
Open this folder in Claude Code (or your IDE's Claude integration) and say:

> _"Read the `raw/` folder, follow `CLAUDE.md`, and compile or update the `/wiki`
> folder with this new material."_

Claude will read the sources, extract concepts, write/update interconnected
`/wiki` pages with `[[wikilinks]]`, and refresh `wiki/index.md`. Because
`CLAUDE.md` lives in this folder, Claude Code loads those rules automatically.

### 3. Visualize in Obsidian (Step 4)
Install [Obsidian](https://obsidian.md) (free) and **Open folder as vault** →
select this `Karpathy-Wiki` folder. Obsidian renders the `[[wikilinks]]` and
gives you an **interactive graph view** showing how concepts, people, and papers
connect. No conversion needed — it's all plain markdown.

> Tip: in Obsidian, point the vault at the whole `Karpathy-Wiki` folder so the
> graph can see both `wiki/` pages and the templates; or open just `wiki/` if you
> want a cleaner graph.

## Why this works

- **Plain markdown** — portable, future-proof, readable with or without any tool.
- **`/raw` immutable** — your originals are never altered; the wiki is always
  reproducible from them.
- **Cross-links + index** — knowledge compounds: each new source connects into
  the existing web instead of piling up in a folder.

See [`CLAUDE.md`](CLAUDE.md) for the exact rules the compiler follows.

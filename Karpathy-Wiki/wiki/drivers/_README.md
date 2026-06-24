---
title: Drivers — Per-Entity Pattern Pages
type: register
tags: [drivers, patterns, ai-context]
last_reviewed: "2026-06-19"
---

# Per-Driver Pattern Pages

A directory of one-page-per-driver "what does the AI know about this person" files. The point is **context the brief can lean on when this driver appears in today's data** — pulled from coaching events, dispatch history, owner conversations, and lessons captured in [[Weekly Retros]] and the [[Decision Journal]].

Without these pages, every safety event for MICHAEL HALL feels novel — the AI has no memory of his past coaching, his historical speed pattern, or what's worked / hasn't with him. With them, the brief can say "MICHAEL HALL — 3rd speeding flag in 90 days, last coached 2026-05-12 by Jeff, told dispatch he disagreed with the speed-limit calibration. Try the Truk-Way maintenance angle (he respected Dan's input there)."

## When to create a page

Create a page when **any** of these is true:

- Driver has appeared on the safety / coaching brief 3+ times in 60 days (pattern emerging — capture what we know)
- Driver triggered a formal progressive-discipline step (see [[Progressive Discipline Policy]])
- Driver has a relationship dimension that explains their behavior (Dan's relationship in particular — see [[Dan Tracking and Driver Connection]])
- Driver is a top performer worth capturing what's working

## File naming

Files use kebab-case of the driver's display name as it appears in Alvys / Samsara:

- `MICHAEL HALL` → `michael-hall.md`
- `LACEY CAMPBELL` → `lacey-campbell.md`
- `JJ HUPF` → `jj-hupf.md`

The brief's entity-context lookup (when it's built) will normalize both ways so casing/spacing doesn't break the match.

## Page template

Each page follows `templates/driver.md` (copy + edit). The minimum useful content:

- **At a glance** — fleet, hire date, current truck, current status
- **Patterns** — what we keep seeing (speed, late deliveries, DVIR misses, etc.)
- **What's worked** — coaching styles, conversations, incentives that landed
- **What hasn't worked** — same, for things that didn't
- **Open** — current open accountability items + last action taken
- **History** — append-only log of consequential events (coachings, escalations, conversations)

Pages are **living documents** — append to them, don't rewrite. The history section is the gold over time.

## Current pages

- [[Michael Hall]] — chronic high-speed driver, coached multiple times (seed example)
- [[Lacey Campbell]] — multi-category accountability subject (CDL, MVR, SambaSafety risk flag) (seed example)

## Connections

- [[Safety Program]] — feeds these pages
- [[Progressive Discipline Policy]] — escalation framework
- [[Dan Tracking and Driver Connection]] — relationship dimension Dan tracks separately
- [[Driver Report Wishlist]] — driver-facing report planned for future
- [[Weekly Retros]] — lessons captured here that reference specific drivers should be cross-linked

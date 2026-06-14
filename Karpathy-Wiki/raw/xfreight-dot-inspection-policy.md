# XFreight DOT inspection policy — 120-day company vs 365-day federal (seed 2026-06-14)

> Core memory. Source: operator clarification 2026-06-14 in response
> to an earlier scorecard interpretation. Captured here as the canon
> any future work on equipment compliance must reference.

## The two windows

There are **two** inspection windows at play, and the brief / KB
must keep them distinct in every label, badge, and copy:

| Window | Length | Who owns it | What "OVERDUE" means |
|---|---|---|---|
| **120-day company policy** | 120 days from the last DOT inspection | XFreight (X-Trux Inc) | **Flagged as needing inspection.** Unit remains in service while ops schedules the inspection — still legal to run under federal rules. Not characterized as "out of service" anywhere. |
| **365-day federal DOT** | 365 days from the last DOT inspection | FMCSA | Out of service per federal rules. Only triggered if the equipment is **245+ days past the company 120d policy** (365 − 120 = 245). |

To be past the federal DOT window, a unit would have to be **245
days past due on the 120-day company policy**. That essentially never
happens in normal operations — by the time the company policy
flags a unit, it gets scheduled and inspected within weeks.

## Why XFreight runs the more-conservative 120-day policy

The federal rule is 365 days. XFreight's voluntary 120-day policy is
about 1/3 the federal window. The reasoning:

1. **Driver safety.** Catching wear, brake/tire condition, and
   electrical issues at the 4-month mark rather than the 12-month
   mark prevents in-service failures and DOT roadside out-of-service
   orders.
2. **Equipment condition / longevity.** Earlier intervention on
   small problems means fewer cascading repairs. Cheaper to fix at
   discovery than after another 8 months of wear.
3. **CSA Maintenance BASIC score.** Every roadside inspection that
   uncovers a defect contributes to the FMCSA Maintenance BASIC
   percentile. The 120d policy keeps that score lower than running
   to the federal limit would.
4. **Catch issues before they happen.** Operational headroom — a
   unit caught on the 120d policy can be scheduled for inspection
   between dispatches, not pulled mid-route.

## Who pays

**X-Trux Inc covers all DOT inspection costs for every piece of
equipment**, regardless of which entity holds title and regardless
of whether the trailer is being pulled by a company driver or an
owner-operator. The cost lives on the X-Trux P&L as part of
maintenance overhead.

## How the brief renders this

The Equipment Compliance pages (page 5 tractors, page 6 trailers)
show **two** summary pills at the top, and they mean different
things:

- **"Annual inspection (365d federal):"** — counts units past the
  federal 365-day window. Should almost always read "All current"
  given the 120d company policy keeps everything well ahead of
  federal.
- **"DOT inspection (120d policy):"** — counts units past the
  company's 120-day policy. This is the one that lights up red and
  drives the inspection-scheduling cadence. "X OVERDUE" here means
  X units need to be inspected per company policy — **not** that
  they're past federal.

The per-unit "DAYS" column shows days remaining (or days past) on
the **120-day company policy** by default, since that's the
operational deadline ops works against.

## Implications for KB / brief code

When writing about inspection status anywhere in this codebase or
KB:

- "Past due" / "OVERDUE" / red badge — must say which window. Default
  to **"flagged as needing inspection (120d company policy)"** unless
  the text explicitly cites the 365d federal rule. Units past only
  the company policy remain in service.
- "Out of service" — reserved language. Use it **only** for units past
  the federal 365d limit (i.e., 245+ days past the 120d company
  policy). Do not say "out of service per company policy" or "out of
  service per FMCSA" for units past only the company threshold.
- The "Equipment inspection backlog" risk register entry and its
  associated playbook are tracking the **120d company policy**
  backlog, not federal-DOT-overdue equipment.

## Related

- `xfreight-playbook-equipment-inspection-backlog.md` — the response
  playbook when units cross the 120d company policy threshold.
- `xfreight-risk-register.md` — the "Equipment inspection backlog"
  entry tracks 120d company-policy backlog.
- `xfreight-safety-program.md` (if/when added) — broader safety
  program context.

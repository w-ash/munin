---
description: Supplements domain schema — per-pill dosing model, regimen, and stack conventions
paths:
  - "Health/Supplements/**"
---

# Supplements

Notes-as-record domain per [[Trackers]]: one note per product, tag `#supplement`, in
`Health/Supplements/entries/`, over `Health/Supplements/Supplements.base`, with a hub note
`Health/Supplements/Stack.md`. Mirrors the `Health/Providers/` shape.

Two standing directives from Ash govern this domain:
- **No nannying.** Record and plan what Ash takes; never editorialize about whether he should.
  Analysis is neutral totals ("stack sums to X; the UL is Y"), never advice-giving.
- **No supplement-company sources.** Any enrichment or research uses nutrition science and
  independent bodies (NIH ODS, Examine, Cochrane), never sellers or supplement-brand blogs.

## Per-pill dosing model (the core rule)

Dose is counted in **pills, not servings.** Frontmatter keeps the label facts faithful (amounts
per label **serving**) and records the regimen in **pills**:

- `pills_per_serving` — the label's serving size, in pills.
- `pills_per_day` — pills Ash actually takes on a dosing day (1 for every item today).
- `ingredients` — a list of `{ name, per_serving, unit, dv_percent }`, amounts **per label
  serving** (verbatim from the Supplement Facts panel). `dv_percent: null` where the label
  prints * / † / ** (DV not established).

Actual daily intake of a nutrient = Σ over active **daily** products of
`per_serving ÷ pills_per_serving × pills_per_day`. Example: Nutricost Magnesium Glycinate at 1
capsule/day = 210 ÷ 3 × 1 = 70 mg/day elemental (not the 210 mg serving). Several products have
multi-pill servings, so 1 pill/day is a fraction of the label serving: B-Complex (2), Magnesium
Glycinate (3), SPM Complex (2), Alpha Lipoic Acid (2), Magtein (3).

## Frontmatter schema (snake_case, per trackers.md)

```yaml
created: "YYYY-MM-DD"
tags: [supplement]
name: ""              # product name, no brand (brand is its own field)
brand: ""
form: ""              # capsule | tablet | softgel | veg capsule | veg softgel | gummy
status: "active"      # active | considering | stopped
purpose: ""           # optional, neutral tag ("sleep", "joints"); leave empty rather than guess
frequency: "daily"    # daily | as-needed
pills_per_day: 1
time_slot: ""         # slot name; empty until scheduling (Phase 3b)
with_food: "either"   # with-food | empty-stomach | either — from the LABEL directions only
pills_per_serving: 1
servings_per_container:
ingredients: []       # list of { name, per_serving, unit, dv_percent } — per label serving
source: "label_ocr"
source_id: ""         # brand-product slug; importers match on it
```

`with_food` is set from what the label directions state; where the label is silent it stays
`either` and any absorption note (fat-soluble, empty-stomach) goes in the body for the
scheduling phase to weigh, not invented into this field.

Body: blockquote one-liner (factual, no health claims), `## Supplement Facts` table (full label,
including blends and other ingredients), `## Directions`, `## Notes`, `## Log`
(`- **[[YYYY-MM-DD]]** — added / dose change / stopped`; the wikilink joins to `Daily/`).

## As-needed items

`frequency: as-needed` marks an item taken occasionally, not on the daily schedule (e.g. the
NATURELO Iron). It keeps a full catalog note, appears in the base's As-needed view, and is
excluded from the daily-intake totals and the regimen.

## Regimen, schedule, and adherence

- **Schedule:** a fixed daily plan across **≤3 time slots**, same times every day. Slots and each
  item's `time_slot` are defined during the evidence review (Phase 3b), against real constraints
  (with-food vs empty-stomach, mineral spacing, AM/PM). The base gains a By-schedule view then.
- **Adherence is exception-only.** The planned regimen is assumed taken. Misses are logged in
  `Stack.md` `## Miss log`, one dated line each. No daily check-off, no streaks, no reminders, no
  script — that is the capture chore the [[Trackers]] framework bans.

## Analysis (pull, not push)

No dashboard. On demand (ad-hoc, or a future `/stack` skill) an agent reads the active daily
notes, computes intake per nutrient from the per-pill model, compares to tolerable upper limits,
and flags timing conflicts (e.g. the two magnesiums; iron vs calcium/coffee spacing). Findings
are neutral totals.

## Evidence-based regimen study

The keep/drop/adjust study uses the vault research harness in `rank` mode (`scripts/vault-tool
research`), candidates = the products, criteria = safety/UL headroom (blocker), efficacy for
Ash's goals (must), dose adequacy (must), timing/absorption (should), redundancy (narrative).
Non-commercial sources; the durable note lands in `Health/`. Accepted changes update product
frontmatter (`pills_per_day`, `time_slot`, `status`) with a cited `## Log` entry.

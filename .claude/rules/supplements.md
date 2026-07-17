---
description: Supplements domain (v2). Per-pill dosing, the substance registry, the effective-dated regimen log, exceptions, and the derived daily intake record
paths:
  - "Health/Supplements/**"
  - "Health/data/reference/substances.jsonl"
  - "Health/data/canonical/stack-*.jsonl"
  - "Health/data/derived/intake-*.jsonl"
  - "Health/data/derived/product-ingredients.jsonl"
---

# Supplements

The supplement domain separates three things that v1 fused into one note: the substance, the
product, and the regimen role it fills. It spans two [[Trackers]] tiers plus a small reference
layer, all driven by `scripts/vault-tool stack` (the `/stack` skill wraps it):

- **Products** are notes-as-record: one note per SKU, tag `#supplement`, in
  `Health/Supplements/entries/`, over `Health/Supplements/Supplements.base`, hub
  `Health/Supplements/Stack.md`. Mirrors the `Health/Providers/` shape.
- **Substances** are reference data: `Health/data/reference/substances.jsonl`, one row per
  canonical nutrient with its unit and upper limit. Hand-maintained, edited in place.
- **The regimen and its deviations** are canonical-files (append-only JSONL):
  `Health/data/canonical/stack-regimen.jsonl` and `stack-exceptions.jsonl`.
- **The daily intake record** is a derived projection: `Health/data/derived/intake-<year>.jsonl`,
  regenerated from the two logs; never the record, always rebuildable.

Two standing directives from Ash govern this domain:
- **No nannying.** Record and plan what Ash takes; never editorialize about whether he should.
  Analysis is neutral totals ("magnesium sums to 118 mg; the UL is 350 mg"), never advice.
- **No supplement-company sources.** Any enrichment uses nutrition science and independent bodies
  (NIH ODS, Examine, Cochrane), never sellers or supplement-brand blogs.

## Per-pill dosing model (the core rule)

Dose is counted in **pills, not servings.** A product note keeps label facts per **serving** and
the regimen records **pills**:

- `pills_per_serving`: the label's serving size, in pills.
- `pills_per_day`: pills Ash takes on a dosing day (a mirror; see below).
- `ingredients`: a list of `{ name, key, per_serving, unit, dv_percent }`, amounts **per label
  serving** (verbatim from the Supplement Facts panel). `dv_percent: null` where the label prints
  * / † / ** (DV not established). `key` maps the label name to a substance in the registry.

Per-pill amount of a substance = `per_serving ÷ pills_per_serving`. A day's planned intake of a
substance = Σ over the active daily regimen of `per_pill × pills_per_day`. Example: Nutricost
Magnesium Glycinate at 1 capsule/day = 210 ÷ 3 × 1 = 70 mg/day elemental (not the 210 mg serving).

## Substance registry

`Health/data/reference/substances.jsonl`, one row per canonical nutrient:

```json
{"key": "magnesium", "name": "Magnesium (elemental)", "unit": "mg", "ul": 350,
 "ul_basis": "supplemental magnesium only", "ul_source": "https://ods.od.nih.gov/...", "notes": ""}
```

- **Minerals are elemental.** The compound weight lives in the ingredient `name` text and (for a
  delivery compound like magnesium L-threonate) in its own pseudo-key that never sums into the
  elemental UL. This keeps cross-product totals and UL checks correct across salt forms.
- **`ul` is `null`** where NIH ODS establishes no upper limit. `ul_basis` carries any nuance the
  bare number hides (folate's UL is defined on synthetic folic-acid mcg, not mcg DFE). `ul_source`
  is an ODS fact sheet.
- **Canonical unit** per substance lives here; every product ingredient must match it (the tool
  warns on a mismatch). Blends map to blend pseudo-keys that sum only within themselves.
- **No alias table.** The label-name to key mapping happens once per product, on the note. Add a
  new registry row before adding a product that introduces a nutrient not yet listed.

## Product-note frontmatter

```yaml
created: "YYYY-MM-DD"
tags: [supplement]
name: ""              # product name, no brand
brand: ""
form: ""              # capsule | tablet | softgel | veg capsule | veg softgel | gummy
status: "active"      # active | considering | stopped   (mirror, tool-owned)
purpose: ""           # optional neutral tag; leave empty rather than guess
frequency: "daily"    # daily | as-needed                (mirror, tool-owned)
pills_per_day: 1      #                                   (mirror, tool-owned)
time_slot: ""         # 1-wake | 2-breakfast | 3-dinner | 4-bedtime  (mirror, tool-owned)
with_food: "either"   # with-food | empty-stomach | either; from the LABEL directions only
pills_per_serving: 1
servings_per_container:
ingredients: []       # list of { name, key, per_serving, unit, dv_percent }; per label serving
source: "label_ocr"
source_id: ""         # brand-product slug; importers and the regimen log match on it
```

**The four mirror fields (`status`, `frequency`, `pills_per_day`, `time_slot`) are tool-owned.**
They exist only so `Supplements.base` views keep working; the truth is the regimen log. Change the
regimen through `stack set`/`stop` (or by telling Claude), never by hand-editing these fields.
`stack check` flags any drift. Everything else on the note (label facts, `ingredients`,
`with_food`, the Supplement Facts table) is note-owned truth: a stopped product's note remains the
permanent record of that formulation.

Body: blockquote one-liner (factual, no health claims), `## Supplement Facts` table, `## Directions`,
`## Notes`, `## Timing`, `## Log` (`- **[[YYYY-MM-DD]]** — added / dose change / stopped`; the
wikilink joins to `Daily/`). The tool appends `## Log` lines on regimen changes.

## Regimen roles and effective dating

A **role** is a stable slug for the job in Ash's day (`magnesium_bedtime`, `magnesium_daytime`,
`zinc`, `iron`, ...), distinct from both substance and product: two roles can share one substance
(the two magnesiums) and one UL. Roles live only in the regimen log and the generated `Stack.md`
block.

`Health/data/canonical/stack-regimen.jsonl` is append-only: `set` (create or supersede a role's
fill: product, pills, slot, frequency) and `stop` (a role ends). Each event carries an `effective`
date decoupled from its write `ts`. Regimen-as-of(D) folds events with `effective <= D` ordered by
`(effective, ts)`; the last `set` wins unless a later `stop` clears the role. Corrections are
superseding events, never edits, so editing today's plan can never rewrite a past day (the
pre-charting trap). Product swaps, dose changes, and start/stop are all just events.

## Adherence: exception-only, derived daily record

The planned regimen is assumed taken. Deviations are logged in
`Health/data/canonical/stack-exceptions.jsonl` (append-only) via `stack log`, which also appends a
dated bullet to `Stack.md`'s `## Exception log`. Kinds: `miss` (scope day | slot | role), `taken`
(an affirmative PRN or off-plan dose), `extra`, `substitute` (one-day product swap), `dose_change`
(one-day pills override). No daily check-off, no streaks, no reminders: that is the capture chore
the [[Trackers]] framework bans. The only capture is logging a deviation.

`Health/data/derived/intake-<year>.jsonl` is the per-day per-substance record. It is **fully
derived**: a day's intake = regimen-as-of(that day) minus/plus that day's exceptions, per the
per-pill math, with `basis` marking each row plan or exception. Nothing per-day persists as truth;
a normal day writes zero bytes. `stack derive --write` regenerates it wholesale for any date range,
so it is always reconstructable and correct through product swaps, dose changes, start/stop, and
PRN items.

## The stack tool and analysis (pull, not push)

`scripts/vault-tool stack` owns all the arithmetic. Read commands: `totals` (current daily intake
per substance vs UL), `uls` (UL-bearing only, with headroom), `day <date>` (a day's resolved
intake), `show --as-of <date>` (the regimen on a date), `history <role>`. Write commands (dry-run
by default, `--write` to apply): `migrate`, `set`, `stop`, `log`, `ingredients`, `derive`,
`project`, `check`. The DuckDB cache exposes `supplement_substances`, `supplement_ingredients`,
`supplement_regimen`, `supplement_exceptions`, `supplement_intake` for ad-hoc range queries via
`vault-tool db query`. No dashboard: analysis runs when asked, and always `derive`s then rebuilds
the cache first so the answer is current. Findings are neutral totals.

## Stack.md

The hub. The regimen list is a generated sentinel block between `<!-- stack:start -->` and
`<!-- stack:end -->`, regenerated by `stack set`/`stop`/`project` from the regimen as of today
(each role rendered with its stored label and timing note). The Goals, "Why it's laid out this
way", Considering, and Evidence-study prose around it are human-owned. The `## Exception log` is
tool-appended.

## Evidence-based regimen study

The keep/drop/adjust study uses the vault research harness in `rank` mode (`scripts/vault-tool
research`): candidates = the products, criteria = safety/UL headroom (blocker), efficacy for Ash's
goals (must), dose adequacy (must), timing/absorption (should), redundancy (narrative).
Non-commercial sources; the durable note lands in `Health/`. Accepted changes go through
`stack set`/`stop` with a cited note, not by editing mirror fields.

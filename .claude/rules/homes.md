---
description: Homes domain schema — candidate home tracker, the actual-vs-potential rubric, and the offer model
paths:
  - "Homes/**"
---

# Homes

Notes-as-record domain per [[Trackers]]: one note per candidate house Ash and Kew are
considering buying (Berkeley, an over-ask market), tag `#home`, in `Homes/entries/`, over
`Homes/Homes.base`. Mirrors the `Health/Providers/` shape (a flat `score` scalar the base sorts
on), scaled up to a weighted multi-criteria rubric. The shared rubric (criteria, weights, 1-5
anchors, offer ratios) lives once in `Homes/Criteria.md`; it is not tagged `#home` and not in the
base, so its nested `criteria` frontmatter list is safe.

The system has three parts: this tracker, the rubric scorer (`vault-tool homes score`), and the
`berkeley-offer-model` research topic (estimate mode) that produces the offer band.

## The rubric (the core model)

Every criterion is scored twice per home plus an effort marker:

- `<key>_actual` (1-5) — current state, as the house is today.
- `<key>_potential` (1-5) — the best it could realistically become after a feasible renovation.
- `<key>_effort` — `easy | moderate | major | infeasible` (or blank when actual == potential).

`vault-tool homes score` reads `Homes/Criteria.md` for the `criteria` list (`key`, `weight`,
`label`) and each home's per-criterion fields, and writes back:

- `score_actual = Σ(weight × actual) / Σ(weight)` — weighted average on the 1-5 scale.
- `score_potential` — same, but with `potential_used = actual if effort == "infeasible" else
  max(actual, potential)`. The **infeasible clamp** is how effort gates the score: upside you
  can't realize doesn't inflate potential.
- `score_upside = score_potential − score_actual`.
- `reno_burden` — weighted mean of effort rank (easy 1 / moderate 2 / major 3) over criteria
  where potential beats actual. Displayed beside the score, never folded into it.

A blank criterion drops out of that home's average (numerator and denominator), so a partly-toured
house isn't scored as if the blank were a zero; the scorer reports coverage (`rated/total`).

## Frontmatter schema (snake_case, per trackers.md)

```yaml
created: "YYYY-MM-DD"
tags: [home]
address: ""             # canonical single value, no "/" (bases trap #5); filled by geocode
neighborhood: ""        # one canonical Berkeley area (Elmwood, Rockridge, ...), no slashes
coordinates: ""         # "lat, lng" — geocode
google_maps_url: ""     # geocode
listing_url: ""
mls: ""
list_price:             # bare int, dollars
beds:                   # bare number
baths:                  # bare number
sqft:                   # bare int
lot_sqft:               # bare int
year_built:             # bare int
days_on_market:         # bare int
price_cuts:             # bare int (count of reductions)
hoa:                    # bare int, monthly, if any
property_type: ""       # single-family | condo | townhouse | multi-unit | tic
status: "candidate"     # candidate | touring | shortlist | offer-prep | offered | under-contract | passed | lost | closed
source: ""              # zillow | redfin | mls | agent  (omit for manual notes)
source_id: ""           # listing/MLS id; importers match on it
last_toured:            # bare date, kept in sync with ## Visits
# --- rubric: one triple per criterion in Homes/Criteria.md ---
light_actual:           # 1-5
light_potential:        # 1-5
light_effort: ""        # easy | moderate | major | infeasible
# ... repeat <key>_actual / <key>_potential / <key>_effort for every criterion key ...
# --- computed by `vault-tool homes score` (do not hand-edit) ---
score_actual:
score_potential:
score_upside:
reno_burden:
est_offer_low:
est_offer_mid:
est_offer_high:
scored_at: ""
```

Body: blockquote one-liner, `## Rubric notes` (why a criterion scored the way it did, per-room
observations), `## Notes`, `## Pros / Cons`, `## Visits` (`- **[[YYYY-MM-DD]]** — who toured,
what stood out`; the wikilink joins to `Daily/`). Keep `last_toured` in sync with the last visit.

## Scoring workflow

1. Tour a home, fill its `<key>_actual` / `<key>_potential` / `<key>_effort` fields (Edit tool for
   one note; `vault-tool fm set` for bulk).
2. `vault-tool geocode lookup --file "Homes/entries/<X>.md" --write` to fill the geo fields (per
   file; `geocode batch` is Travel-scoped, don't use it here).
3. `vault-tool homes score` (dry-run) to preview, then `--write` to persist the computed scalars.
   Re-run after any rating change or after the offer band updates in `Homes/Criteria.md`.

## Offer model

`Homes/Criteria.md` holds `offer_ratio_low/mid/high` (sale-to-list ratios) from the
`berkeley-offer-model` estimate topic. `homes score` fills `est_offer_{low,mid,high} =
round(list_price × ratio)`. It skips and reports when the ratios or `list_price` are absent. A
genuinely stale or red-hot listing can carry a hand-set ratio, documented in its `## Notes`.

## Sign-off

The criteria set, weights, and the `Homes.base` are shared decisions: Ash signs off (CLAUDE.md
rule #5) before they're relied on. The scorer and schema are Claude's to maintain.

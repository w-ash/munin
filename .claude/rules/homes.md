---
description: Home Search project tracker schema — candidate home tracker, the actual-vs-potential rubric, and the offer model
paths:
  - "Projects/Home Search/**"
---

# Homes

Project-scoped notes-as-record tracker, part of the [[Home Search]] project rather than a
permanent root-level life domain (the search ends when a house is bought, so the tracker lives
under `Projects/Home Search/` and archives with the project). Conventions follow [[Trackers]]:
one note per candidate house Ash and Kew are considering buying (Berkeley, an over-ask market),
tag `#home`, in `Projects/Home Search/Homes/entries/`, over
`Projects/Home Search/Homes/Homes.base`. Mirrors the `Health/Providers/` shape (a flat `score` scalar the base sorts
on), scaled up to a weighted multi-criteria rubric. The shared rubric (criteria, weights, 1-5
anchors, offer ratios) lives once in `Projects/Home Search/Homes/Criteria.md`; it is not tagged `#home` and not in the
base, so its nested `criteria` frontmatter list is safe.

The system has four parts: this tracker, the rubric scorer (`vault-tool homes score`), the
`berkeley-offer-model` research topic (estimate mode) that produces the offer band, and the
comp-based valuation (`vault-tool homes value`, see below) that predicts a dollar sale price.

## The rubric (the core model)

Every criterion is scored twice per home plus an effort marker:

- `<key>_actual` (1-5) — current state, as the house is today.
- `<key>_potential` (1-5) — the best it could realistically become after a feasible renovation.
- `<key>_effort` — `easy | moderate | major | infeasible` (or blank when actual == potential).

`vault-tool homes score` reads `Projects/Home Search/Homes/Criteria.md` for the `criteria` list (`key`, `weight`,
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
# --- rubric: one triple per criterion in Projects/Home Search/Homes/Criteria.md ---
light_actual:           # 1-5
light_potential:        # 1-5
light_effort: ""        # easy | moderate | major | infeasible
# ... repeat <key>_actual / <key>_potential / <key>_effort for every criterion key ...
# --- optional objective valuation inputs (for `homes value`; see below) ---
garage:                 # bare int, off-street spaces (optional)
adu:                    # bare int, 0/1 has a unit (optional)
condition:              # bare int, 1-5 objective state, distinct from condition_actual (optional)
# --- computed by `vault-tool homes score` (do not hand-edit) ---
score_actual:
score_potential:
score_upside:
reno_burden:
est_offer_low:
est_offer_mid:
est_offer_high:
scored_at: ""
# --- computed by `vault-tool homes value` (do not hand-edit) ---
predicted_price:        # bare int, comp-adjusted sale-price estimate
predicted_low:          # bare int, 90% band low
predicted_high:         # bare int, 90% band high
implied_over_list:      # bare float, predicted_price / list_price
valuation_confidence: "" # high | medium | low
comps_used:             # bare int
valued_at: ""
```

Body: blockquote one-liner, `## Rubric notes` (why a criterion scored the way it did, per-room
observations), `## Notes`, `## Pros / Cons`, `## Visits` (`- **[[YYYY-MM-DD]]** — who toured,
what stood out`; the wikilink joins to `Daily/`). Keep `last_toured` in sync with the last visit.

## Scoring workflow

1. Tour a home, fill its `<key>_actual` / `<key>_potential` / `<key>_effort` fields (Edit tool for
   one note; `vault-tool fm set` for bulk).
2. `vault-tool geocode lookup --file "Projects/Home Search/Homes/entries/<X>.md" --write` to fill the geo fields (per
   file; `geocode batch` is Travel-scoped, don't use it here).
3. `vault-tool homes score` (dry-run) to preview, then `--write` to persist the computed scalars.
   Re-run after any rating change or after the offer band updates in `Projects/Home Search/Homes/Criteria.md`.

## Offer model

`Projects/Home Search/Homes/Criteria.md` holds `offer_ratio_low/mid/high` (sale-to-list ratios) from the
`berkeley-offer-model` estimate topic. `homes score` fills `est_offer_{low,mid,high} =
round(list_price × ratio)`. It skips and reports when the ratios or `list_price` are absent. A
genuinely stale or red-hot listing can carry a hand-set ratio, documented in its `## Notes`.

## Valuation model

`vault-tool homes value` predicts a dollar sale price per home from comparable sales, adjusted for
how the subject differs from each comp, then derives over/under-list. It complements the rubric
(desirability) with an objective cost-to-win number; the two sit side by side in the base. Three
inputs:

- **Comps store** — `Projects/Home Search/Homes/data/comps.csv`, one row per comparable sale, linked to a subject by
  slug (the home filename: `2117 Grant St.md` → `2117-grant-st`). Canonical-files tier. Rows arrive
  from the RentCast fetcher, a buyer's-agent CMA, or hand entry; `source` marks provenance
  (`rentcast` prices are listing-derived approximations, `agent`/`manual`/`county` are recorded
  sales). Columns: subject, address, sale_price, sale_date, beds, baths, sqft, lot_sqft, year_built,
  dist_mi, garage, adu, condition, source, source_id.
- **Adjustment schedule** — `Projects/Home Search/Homes/Adjustments.md` frontmatter `adjustments` list: per feature a
  `unit` and a sourced low/mid/high dollar range. Each comp is adjusted by `mid × (subject − comp)`
  summed over the features present on both. Shaped like `Criteria.md` (shared config, not tagged,
  not in the base). Derived by paired-sales research; empty until that runs (the command then falls
  back to the prior).
- **Offer-ratio prior** — the same `offer_ratio_*` in `Criteria.md`, used as the fallback when a
  home has no usable comps (basis `prior`, low confidence). Degrades to exactly the `est_offer`
  band.

Writes back the computed fields above plus a `## Valuation` body table (comps used + per-comp
adjustments, auditable). Same dry-run / `--write` / all-or-nothing batch discipline as `homes
score`. Confidence drops on few comps or high dispersion; the band widens accordingly.

### Fetching comps

`vault-tool homes comps fetch --file "Projects/Home Search/Homes/entries/<X>.md"` pulls comps from the RentCast free tier
(50 requests/month; needs `RENTCAST_API_KEY` in `.env`). Dry-run previews the request without
spending one; `--write` calls the API and appends deduped rows (one request returns ~15 comps).

### Valuation workflow

1. `vault-tool homes comps fetch --file "Projects/Home Search/Homes/entries/<X>.md" --write` (or hand-enter comps).
2. Derive/refresh the adjustment ranges in `Projects/Home Search/Homes/Adjustments.md` (paired sales on the comps).
3. `vault-tool homes value` (dry-run) to preview, then `--write` to persist.

## Sign-off

The criteria set, weights, the adjustment schedule (`Projects/Home Search/Homes/Adjustments.md`), and the `Homes.base`
are shared decisions: Ash signs off (CLAUDE.md rule #5) before they're relied on. The scorer,
valuation, and schema are Claude's to maintain.

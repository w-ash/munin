---
name: stack
description: Analyze or update the supplement stack via `scripts/vault-tool stack`. Use for intake totals and UL headroom, a given day's exact intake, logging an exception (a miss, a PRN dose taken, anything off-plan), or a regimen change (product swap, dose change, start/stop). Triggers on "what am I taking", "am I over any limits", "I missed my bedtime dose", "I took an iron today", "I switched magnesium brands", "/stack".
user_invocable: true
---

# Supplement stack

Pull-analysis and low-friction capture for the supplement tracker. All numeric work (per-pill math, the regimen fold, exception folding, UL comparison) is owned by `scripts/vault-tool stack`; this skill picks the right subcommand and reports neutral totals.

Two standing directives govern every reply here:
- **No nannying.** Report and record what Ash takes; never editorialize about whether he should. Analysis is neutral totals ("magnesium sums to 118 mg; the UL is 350 mg"), never advice.
- **No supplement-company sources.** Any enrichment uses NIH ODS, Examine, or Cochrane, never sellers or brand blogs.

## The model (what lives where)

- **Products**: 19 notes in `Health/Supplements/entries/*.md`, each with label facts and an `ingredients` list; every ingredient carries a canonical substance `key`.
- **Substances**: `Health/data/reference/substances.jsonl`, one row per nutrient with its canonical unit and NIH ODS upper intake level (UL) where one exists.
- **Regimen**: `Health/data/canonical/stack-regimen.jsonl`, append-only `set`/`stop` events, effective-dated. The fold gives the regimen as of any date. The four regimen fields on each product note (`status`, `pills_per_day`, `time_slot`, `frequency`) are tool-owned mirrors; never hand-edit them.
- **Exceptions**: `Health/data/canonical/stack-exceptions.jsonl`, append-only deviations (miss / taken / extra / substitute / dose_change).
- **Derived**: `Health/data/derived/intake-<year>.jsonl`, the per-day per-substance record, regenerated from the regimen and exceptions. Never the record; always rebuildable.

All of it is queryable in DuckDB as `supplement_substances`, `supplement_ingredients`, `supplement_regimen`, `supplement_exceptions`, `supplement_intake` via `scripts/vault-tool db query`.

## Before answering an analysis question

Refresh the derived record and the query cache, then read:

```
scripts/vault-tool stack derive --write
scripts/vault-tool db rebuild --write
```

These are pull steps: run them when asked a question, not on a schedule. A normal day writes nothing on its own.

## Answering questions

- **"What am I taking / totals / am I over any limits?"** -> `scripts/vault-tool stack totals` (all substances) or `scripts/vault-tool stack uls` (UL-bearing only, with headroom and an `overUl` list). Report the daily amount, the UL, and the headroom plainly. When a total shows over its UL, state the number and the `ul_basis` caveat verbatim (e.g. folate's UL is defined on synthetic folic-acid mcg, not mcg DFE), and stop; do not advise.
- **"What did I take on <date>?"** -> `scripts/vault-tool stack day <date>`. Returns per-substance totals for that day with each row's `basis` (plan or exception) and the day's exceptions.
- **"Over a date range / trend for nutrient N"** -> `scripts/vault-tool db query "SELECT date, sum(amount) FROM supplement_intake WHERE key='magnesium' AND date BETWEEN '...' AND '...' GROUP BY 1 ORDER BY 1"`.
- **"When did I change / product history for a role"** -> `scripts/vault-tool stack history <role>`, or `scripts/vault-tool stack show --as-of <date>` for the whole regimen on a date.

## Logging an exception (the only capture)

When Ash says he missed a dose, took a PRN item, or took anything off the plan, append one event with `scripts/vault-tool stack log <kind> ... --write`. Dry-run first (omit `--write`) and show the planned line. It dual-writes the JSONL event and a dated bullet in `Stack.md`'s `## Exception log`.

- Missed the whole day: `stack log miss --date <d> --scope day --write`
- Missed a slot: `stack log miss --date <d> --scope slot --slot 4-bedtime --write`
- Missed one item: `stack log miss --date <d> --scope role --role vitamin_c --write`
- Took a PRN or anything off-plan: `stack log taken --date <d> --role iron --pills 1 --write` (or `--product <source_id>` for something with no role)
- Extra pills of a regimen item: `stack log extra --date <d> --role magnesium_bedtime --pills 1 --write`
- One-day substitution: `stack log substitute --date <d> --role vitamin_c --product <source_id> --write`
- One-day dose override: `stack log dose_change --date <d> --role ashwagandha --pills 2 --write`

Date defaults to today. Add `--note "..."` for context. A substituted or taken product must have a catalog note; if it does not, offer to create a minimal one first.

## Changing the regimen (not a one-day exception)

A durable change (new brand, permanent dose change, adding or dropping an item) is a regimen event, not an exception:

- Swap or dose change: `scripts/vault-tool stack set <role> --product <source_id> --pills <n> --effective <date> --slot <slot> [--label "..."] [--timing-note "..."] [--note "..."] --write`
- Stop an item: `scripts/vault-tool stack stop <role> --effective <date> --note "..." --write`

`set`/`stop` append the event, reconcile the product-note mirrors to the regimen as of today, append a `## Log` line to the affected notes, and regenerate the `Stack.md` regimen block (the sentinel between `<!-- stack:start -->` and `<!-- stack:end -->`). Dry-run first. After any change, `scripts/vault-tool stack check` confirms no mirror drift.

## Adding a new product

New product = a new note in `Health/Supplements/entries/` per `.claude/rules/supplements.md` (label facts, per-pill model, a `key` on every ingredient from `substances.jsonl`; add a substance row first if a nutrient is missing). Then `stack set <role> ... --effective <date> --write` to put it in the regimen. Run `stack ingredients --write` to refresh the derived per-pill file.

## After any write

Regenerate and re-cache so a follow-up query is current:

```
scripts/vault-tool stack derive --write
scripts/vault-tool db rebuild --write
```

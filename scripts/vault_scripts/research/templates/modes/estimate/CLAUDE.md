# CLAUDE.md: {{TOPIC_TITLE}}

Quantitative-sizing research into: **{{RESEARCH_QUESTION}}**

Guiding lens: **{{GUIDING_LENS}}** (the angle that decides how the target decomposes and which factors carry the uncertainty).

**Audience:** {{AUDIENCE}}. Deliverables read in a neutral voice: no second person, no request-framed asides, don't state the audience inside the doc.

This is an **`estimate`** topic: the question is "how big / how much, now?", and the answer is a **magnitude with a range**, not a point. The target is decomposed into sub-factors (a Fermi decomposition), each a lognormal read from a low/high interval, and the scorer propagates the uncertainty to a median and a confidence interval. The work runs in **three planes** that never clobber each other:

- **Evidence** (`data/*.csv`): the append-only database and source of truth. Rules: `.claude/rules/evidence.md`.
- **Synthesis** (`SYNTHESIS.md`): regenerated from the evidence after each pass; never hand-edited between re-syncs, and it carries only what the evidence supports.
- **Narrative** (`narrative/`): hand-authored, audience-shaped docs; never auto-generated. Opinions, implications, and open questions live here. See `narrative/README.md`.

## The target

**{{TARGET_QUANTITY}}**

The estimate is only as good as the decomposition: factors must be independent (no double-counting) and multiply/add to the target. Present-state only: this sizes what *is*, not what *will be*.

## Files

- `data/factors.csv`: the decomposition, one row per factor (`factor_id`, `name`, `op`, `low`, `mid`, `high`, `distribution`, `notes`). `op` is how the factor enters the formula (`mul`/`div` within a product term, `add`/`sub` starting a new term); `low`/`high` bound a 90% interval and `mid` is the median (blank = geometric mean of low/high).
- `data/evidence.csv`: append-only, one row per sourced observation, keyed by `factor_id` and carrying a verbatim `quote` and a `source_url` backing that factor's value/range.
- `data/citations.csv`: written by `vault-tool research verify`, the per-row citation verdicts.
- `research.toml`: topic config (interval width, Monte Carlo samples/seed, Sheet id).
- `SYNTHESIS.md`, `narrative/`, `HANDOFF.md`, `FINDER-PROMPT.md`: as in every topic.

## Factors

{{FACTORS_LIST}}

## How work happens

- **Run a pass:** the `run-pass` skill from the research plugin; `HANDOFF.md` is the canonical step list.
- **Store conventions and the propagation model:** `.claude/rules/evidence.md`.
- **Validate / score:** `vault-tool research check`, `vault-tool research verify` (mechanical citation check on the factor sources), `vault-tool research score` (target median + interval, and the dominant-uncertainty factor).
- **Spawning agents or workflows:** `.claude/rules/orchestration.md`.

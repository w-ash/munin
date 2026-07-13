# CLAUDE.md: {{TOPIC_TITLE}}

Comparative-ranking research into: **{{RESEARCH_QUESTION}}**

Guiding lens: **{{GUIDING_LENS}}** (the angle that decides which criteria matter and how much).

**Audience:** {{AUDIENCE}}. Deliverables read in a neutral voice: no second person, no request-framed asides, don't state the audience inside the doc.

This is a **`rank`** topic: the question is "which candidate is best?", and the answer is a fit ranking of candidates against a weighted rubric, each cell backed by graded sources. The work runs in **three planes** that never clobber each other:

- **Evidence** (`data/*.csv`): the append-only database and source of truth. Rules: `.claude/rules/evidence.md`.
- **Synthesis** (`SYNTHESIS.md`): regenerated from the evidence after each pass; never hand-edited between re-syncs, and it carries only what the evidence supports.
- **Narrative** (`narrative/`): hand-authored, audience-shaped docs; never auto-generated. Opinions, implications, and open questions live here. See `narrative/README.md`.

## Files

- `data/candidates.csv`: the options being compared (`candidate_id`, `name`).
- `data/criteria.csv`: the weighted rubric (`criterion_id`, `text`, `weight`, `tier`). `tier` is one of `blocker` / `must` / `should` / `nice`.
- `data/evidence.csv`: append-only source-graded evidence, each row attached to a `cell_id` (`<candidate_id>--<criterion_id>`) and carrying `source_tier`, `strength`, `bearing`, and a verbatim `quote`. Fit is never stored; the CLI computes it (`vault-tool research score`).
- `data/citations.csv`: written by `vault-tool research verify`, the per-row citation verdicts the scorer folds in.
- `research.toml`: topic config (certainty parameters, blocker threshold, Sheet id).
- `SYNTHESIS.md`, `narrative/`, `HANDOFF.md`, `FINDER-PROMPT.md`: as in every topic.

## The rubric

**Candidates:** {{CANDIDATES_LIST}}

**Criteria (weight, tier):** {{CRITERIA_LIST}}

The grid is candidates x criteria; each cell is a claim scored by the same evidence engine as `verify`. The rubric is revisable: a pass may re-weight a criterion or promote one to `blocker` as the comparison sharpens. Record every change in the HANDOFF changelog.

## How work happens

- **Run a pass:** the `run-pass` skill from the research plugin; `HANDOFF.md` is the canonical step list.
- **Store conventions and scoring model:** `.claude/rules/evidence.md`.
- **Validate / score:** `vault-tool research check`, `vault-tool research verify` (mechanical citation check, writes verdicts), `vault-tool research score` (candidate fit ranking).
- **Spawning agents or workflows:** `.claude/rules/orchestration.md`.

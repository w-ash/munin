# CLAUDE.md: {{TOPIC_TITLE}}

Claim-verification research into: **{{RESEARCH_QUESTION}}**

Guiding lens: **{{GUIDING_LENS}}** (the angle that decides which claims are load-bearing and which are incidental).

**Audience:** {{AUDIENCE}}. Deliverables read in a neutral voice: no second person, no request-framed asides, don't state the audience inside the doc.

This is a **`verify`** topic: the question is "are these claims true?", and the answer is a per-claim certainty backed by graded sources. The work runs in **three planes** that never clobber each other:

- **Evidence** (`data/*.csv`): the append-only database and source of truth. Rules: `.claude/rules/evidence.md`.
- **Synthesis** (`SYNTHESIS.md`): regenerated from the evidence after each pass; never hand-edited between re-syncs, and it carries only what the evidence supports.
- **Narrative** (`narrative/`): hand-authored, audience-shaped docs; never auto-generated. Opinions, implications, and open questions live here. See `narrative/README.md`.

## Files

- `data/claims.csv`: the claims under test (`claim_id`, `claim`, `notes`).
- `data/evidence.csv`: append-only source-graded evidence, each row attached to a `claim_id` and carrying `source_tier` (primary / community / secondary / weak), `strength` (weak / moderate / strong), `bearing` (supports / refutes), and a verbatim `quote`. Certainty is never stored; the CLI computes it (`vault-tool research score`).
- `data/citations.csv`: written by `vault-tool research verify`, the per-row citation verdicts the scorer folds in.
- `research.toml`: topic config (claim id prefix, certainty parameters, Sheet id).
- `SYNTHESIS.md`, `narrative/`, `HANDOFF.md`, `FINDER-PROMPT.md`: as in every topic (synthesis plane, narrative plane, rolling baton, canonical agent prompt).

## Claims under test

{{CLAIMS_LIST}}

The claim list is revisable: a pass may split a claim that turns out to conflate two, or retire one that is out of scope. Record every change in the HANDOFF changelog.

## How work happens

- **Run a pass:** the `run-pass` skill from the research plugin; `HANDOFF.md` is the canonical step list.
- **Store conventions and certainty model:** `.claude/rules/evidence.md`.
- **Validate / score:** `vault-tool research check`, `vault-tool research verify` (mechanical citation check, writes verdicts), `vault-tool research score` (per-claim certainty).
- **Spawning agents or workflows:** `.claude/rules/orchestration.md`.

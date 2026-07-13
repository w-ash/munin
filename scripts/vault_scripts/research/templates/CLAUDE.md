# CLAUDE.md: {{TOPIC_TITLE}}

Evidence-based research into: **{{RESEARCH_QUESTION}}**

Guiding lens: **{{GUIDING_LENS}}** (the angle that decides which findings matter and which are noise).

**Audience:** {{AUDIENCE}}. Deliverables read in a neutral voice: no second person, no request-framed asides, don't state the audience inside the doc.

The work runs in **three planes** that never clobber each other:

- **Evidence** (`data/*.csv`): the append-only database and source of truth. Rules: `.claude/rules/evidence.md`.
- **Synthesis** (`SYNTHESIS.md`): regenerated from the evidence after each pass; never hand-edited between re-syncs, and it carries only what the evidence supports.
- **Narrative** (`narrative/`): hand-authored, audience-shaped docs; never auto-generated. Opinions, implications, and open questions live here. See `narrative/README.md`.

## Files

- `data/taxonomy.csv`, `data/evidence.csv`, `data/sources.csv`: the database. Confidence is never stored; the `research` CLI computes it (`vault-tool research status`).
- `research.toml`: topic config (unit noun, canonical unit list, confidence parameters, Sheet id).
- `SYNTHESIS.md`: the synthesis plane.
- `narrative/`: the narrative plane.
- `HANDOFF.md`: the rolling baton: current assignment, how-to, queue, changelog. All transient state lives there.
- `FINDER-PROMPT.md`: canonical research-agent prompt, versioned; never improvise a per-pass prompt.

## Categories

{{TAXONOMY_LIST}}

The taxonomy is open; promotion bar and boundaries in `.claude/rules/evidence.md`, tagging precedents in `HANDOFF.md`.

## How work happens

- **Run a pass:** the `run-pass` skill from the research plugin; `HANDOFF.md` is the canonical step list.
- **Store conventions and confidence model:** `.claude/rules/evidence.md`.
- **Validate / score / share:** `vault-tool research check`, `vault-tool research status`, `vault-tool research sync` (Google Sheet mirror).
- **Spawning agents or workflows:** `.claude/rules/orchestration.md`.

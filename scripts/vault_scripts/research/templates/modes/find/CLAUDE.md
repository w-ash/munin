# CLAUDE.md: {{TOPIC_TITLE}}

Enumeration research into: **{{RESEARCH_QUESTION}}**

Guiding lens: **{{GUIDING_LENS}}** (the angle that decides which entities belong in the frame and which attributes are load-bearing).

**Audience:** {{AUDIENCE}}. Deliverables read in a neutral voice: no second person, no request-framed asides, don't state the audience inside the doc.

This is a **`find`** topic: the question is "who/what is every entity matching this filter, and what are its attributes?", and the answer is a roster scored by **coverage** (recall against the frame) and **per-field verification** (each attribute traced to a source that checks out). The work runs in **three planes** that never clobber each other:

- **Evidence** (`data/*.csv`): the append-only database and source of truth. Rules: `.claude/rules/evidence.md`.
- **Synthesis** (`SYNTHESIS.md`): regenerated from the evidence after each pass; never hand-edited between re-syncs, and it carries only what the evidence supports.
- **Narrative** (`narrative/`): hand-authored, audience-shaped docs; never auto-generated. Opinions, implications, and open questions live here. See `narrative/README.md`.

## The frame

**{{FRAME_DEFINITION}}**

The frame is the anti-drift anchor: it is the named, bounded population the roster enumerates, so "complete" is measurable and a coverage gap is nameable rather than silent. If a pass has to widen or narrow it, record the change in the HANDOFF changelog. `research.toml` `[find] expected_count` records the frame size when it is a known-size set (recall = found / expected); leave it blank when the size is unknown and read the saturation curve instead.

## Files

- `data/entities.csv`: the roster, one row per entity (`entity_id`, `name`, `in_frame`, plus one column per attribute holding the extracted value). Wide table; `in_frame` marks membership.
- `data/attributes.csv`: the fields to extract (`attribute_id`, `name`, `required`). A `required` field must be filled for an entity to count as complete.
- `data/evidence.csv`: append-only, one row per sourced observation, keyed by `cell_id` (`<entity_id>--<attribute_id>`) and carrying a verbatim `quote` and a `source_url`. Coverage is never stored; the CLI computes it (`vault-tool research score`).
- `data/citations.csv`: written by `vault-tool research verify`, the per-cell citation verdicts the scorer folds in as the field-verified signal.
- `research.toml`: topic config (frame, expected_count, Sheet id).
- `SYNTHESIS.md`, `narrative/`, `HANDOFF.md`, `FINDER-PROMPT.md`: as in every topic.

## Attributes to extract

{{ATTRIBUTES_LIST}}

## Roster so far

{{ENTITIES_LIST}}

## How work happens

- **Run a pass:** the `run-pass` skill from the research plugin; `HANDOFF.md` is the canonical step list.
- **Store conventions and coverage model:** `.claude/rules/evidence.md`.
- **Validate / score:** `vault-tool research check`, `vault-tool research verify` (mechanical per-field citation check, writes verdicts), `vault-tool research score` (recall + per-field verification).
- **Spawning agents or workflows:** `.claude/rules/orchestration.md`.

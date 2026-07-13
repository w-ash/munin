# HANDOFF: {{TOPIC_TITLE}}

A rolling baton. Each session does **one batch (~5 units)**, updates the data CSVs, then **rewrites the "Your assignment" section for the next session** and appends to the changelog. Read `CLAUDE.md` first; it has the framework, scope, and confidence model. This doc is the task queue, not a re-explanation.

**Mutability rule:** only the "Your assignment" section is rewriteable. The Changelog, Queue history ("Done" lines), and Sourcing notes are append-only: add to them, never tidy, rewrite, or summarize them.

---

## Your assignment (Pass 1)

Research these **units** (top of the queue):

1. {{UNIT_1}}
2. {{UNIT_2}}
3. {{UNIT_3}}
4. {{UNIT_4}}
5. {{UNIT_5}}

Goal for each: findings across the categories in CLAUDE.md, captured verbatim with working source URLs. Pass 1 establishes the taxonomy's first contact with reality; expect to refine category definitions and boundaries as you go, and note every refinement in the changelog.

**Priorities:** all categories are unestablished at Pass 1; spread effort rather than going deep on one. Watch for material warranting a **brand-new category** (see CLAUDE.md open taxonomy).

---

## How to do it

All files are in this topic folder. The `data/` CSVs are the source of truth.

1. **Search**, unit by unit, spawning one finder agent per unit with `FINDER-PROMPT.md` (fill the placeholders; don't improvise the prompt: edit the file, bump its version, and add a changelog note if it must evolve). Check the **Sourcing notes** below first. Search-first; don't assert findings from memory.
2. **Critic check** before logging: one critic agent (distinct from the finders) re-checks each category id against the boundary definitions, spot-checks 20% or more of source URLs ("bot-blocked but independently search-confirmed" is a pass), and confirms or rejects every finder-claimed divergence. No `-div` row is logged unconfirmed. Adjudicate its verdicts yourself (the critic advises, the main loop decides); record the verdict in your changelog entry.
3. **Append to `data/evidence.csv`**, one row per finding. Columns:
   `evidence_id, pass, date_captured, unit, category_id, finding_verbatim, detail_quote, source_type, source_url, published_date, notes`
   - **Unit strings must exactly match `research.toml` `units`** (which mirrors the queue below); `vault-tool research check` enforces this. Subsidiary evidence logs under the parent unit.
   - Continue evidence ids from the last used (start at **E001**). Source ids start at **S001**.
   - **Verbatim capture**; don't translate into our jargon.
   - **One category id per row.** Divergence gets the `-div` suffix (critic-confirmed only); near-misses go to `taxonomy.csv` `notes_coverage` instead of evidence; a searched-but-empty category gets a structured note there too: `Null (Pass N): <unit> - <interpretation>`.
   - If a finding fits no category, add a new `Cn` row in `data/taxonomy.csv` (define it and its boundary) and tag the evidence with the new id; don't force-fit. Promotion bar in `.claude/rules/evidence.md`.
   - Append-only, with the carve-outs in `.claude/rules/evidence.md`: tag corrections in place, `VOID` to retire a row, supersede with a newer-dated row for content changes.
4. **Append each new URL to `data/sources.csv`** (dedupe; continue source ids).
5. **Update the synthesis fields in `data/taxonomy.csv`** (examples, synthesis_notes, notes_coverage). There are no computed columns on disk; confidence comes from the CLI.
6. **Run `vault-tool research check`**; require **zero errors** before moving on.
7. **Run `vault-tool research status`** and read the confidence table.
8. **Re-sync `SYNTHESIS.md`**: its coverage and confidence tables must match the `vault-tool research status` output; refine prose where findings change the synthesis. **No** verbatim findings, quotes, or URLs in the synthesis; those stay in `data/`. Keep the neutral voice from CLAUDE.md.
9. Optionally **share**: `vault-tool research sync` pushes the store and computed confidence to the Google Sheet mirror (needs `sheet_id` in `research.toml`).

## Acceptance criteria (don't hand off until all true)

- 3 or more evidence rows per assigned unit, each with a working source URL.
- Every evidence row has a valid category id and verbatim capture.
- Every row was checked against its category's purpose before logging; near-misses went to taxonomy notes, not evidence.
- A critic agent (not a finder) reviewed the category ids, spot-checked 20% or more of source URLs, and confirmed or rejected every claimed divergence; verdict recorded in the changelog entry.
- Every searched-but-empty priority category has a `Null (Pass N)` note in taxonomy `notes_coverage`.
- Unit strings match `research.toml` `units` exactly.
- `vault-tool research check` reports zero errors.
- SYNTHESIS.md coverage and confidence tables match the `vault-tool research status` output.

## Sourcing notes (by unit / source; accumulate these, they compound)

- (none yet; record access tricks, paywalls, bot-blocks, and reliable mirrors as you find them)

## Before you finish: rotate the baton

1. Move your units into the **Changelog** below (date, pass #, evidence id range, critic verdict).
2. **Rewrite the "Your assignment" section** above for the next session: bump the pass number, pull the next ~5 units off the queue, and state which categories are thin and need hunting.
3. Update the **Queue** so the next session sees what's left, and append the next batch's canonical names to `research.toml` `units`.
4. **Every 3rd pass**: run the taxonomy audit (full evidence log vs. boundaries; correct tags in place; review accumulated `-div` rows, and when 2 or more units diverge the same way, amend the category definition or split a new category, then re-judge the old `-div` rows; re-confirm the watch list; log it).

---

## Queue (running order)

**Assigned now (Pass 1):** {{UNIT_1}}, {{UNIT_2}}, {{UNIT_3}}, {{UNIT_4}}, {{UNIT_5}}

**Up next (Pass 2+), in order:** {{QUEUE_REMAINDER}}

---

## Changelog

- **Seeded ({{DATE}}):** Topic spun up from the research plugin templates (CSV store scaffolded, taxonomy seeded, queue ordered). No passes run yet.

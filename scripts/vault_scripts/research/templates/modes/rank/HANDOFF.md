# HANDOFF: {{TOPIC_TITLE}}

A rolling baton. Each session works **one batch of candidates** (or fills thin cells across candidates), updates the data CSVs, then **rewrites the "Your assignment" section for the next session** and appends to the changelog. Read `CLAUDE.md` first; it has the framework, scope, rubric, and scoring model. This doc is the task queue, not a re-explanation.

**Mutability rule:** only the "Your assignment" section is rewriteable. The Changelog and Sourcing notes are append-only.

---

## Your assignment (Pass 1)

Evaluate these **candidates** across the full rubric (top of the queue):

1. {{CANDIDATE_1}}
2. {{CANDIDATE_2}}
3. {{CANDIDATE_3}}

Goal for each: evidence on every criterion (concentrated on the `blocker` and `must` criteria), graded by source tier and strength, captured verbatim with working URLs. Pass 1 establishes the grid's first contact with the sources; expect to refine criterion wording and weights, and note every change in the changelog.

**Priorities:** blocker and must criteria first; a blocker you cannot resolve decides the ranking. Leave a genuinely unknown cell empty (it sits at the prior) rather than guessing.

---

## How to do it

All files are in this topic folder. The `data/` CSVs are the source of truth.

1. **Search**, candidate by candidate, spawning one finder agent per candidate with `FINDER-PROMPT.md` (fill the placeholders including the criteria block; don't improvise the prompt). Check the **Sourcing notes** below first. Search-first; don't assert from memory.
2. **Critic check** before logging: one critic agent (distinct from the finders) re-checks each row's `cell_id`, `bearing`, `source_tier`, and `strength` against the source, and confirms or rejects every claimed refutation. Guard against grade inflation, and against length/self-preference bias in the sources. No row logs with an unconfirmed grade. Adjudicate its verdicts yourself; record the verdict in your changelog entry.
3. **Append to `data/evidence.csv`**, one row per piece of evidence. Columns:
   `evidence_id, pass, date_captured, cell_id, source_tier, strength, bearing, quote, source_type, source_url, published_date, notes`
   - `cell_id` is `<candidate_id>--<criterion_id>` and must resolve to a real candidate x criterion (`vault-tool research check` enforces this).
   - Continue evidence ids from the last used (start at **E001**).
   - **Verbatim capture** into `quote`. Retire a bad row with `cell_id` = `VOID`; supersede a changed source with a newer-dated row.
4. **Run `vault-tool research verify`**: it checks every cited quote is on the page (Wayback fallback), writing verdicts to `data/citations.csv`. Resolve every `quote_missing` and `dead` row before the gate. `unfetchable` is acceptable when independently search-confirmed.
5. **Gate:** run `vault-tool research check`; zero errors before anything else proceeds.
6. **Score:** run `vault-tool research score` and read the fit ranking, the blocked candidates, and each candidate's `least_resolved` criterion and evidence gaps.
7. **Sharpen the top of the ranking:** for the leading candidates and any that are close, spawn a fresh-context skeptic to attack their `blocker`/`must` cells (hunt refuting primary sources and superseding information), and run a small **pairwise** comparison of the leaders with 2-3 independent judges, reporting order-dependent disagreement. Confirmed contradictions become normal `refutes` rows applied centrally and verified in step 4. Re-run `vault-tool research score` afterward.
8. **Re-sync `SYNTHESIS.md`:** its ranking and per-candidate tables must match `vault-tool research score`. Synthesis only: no verbatim quotes or URLs, no "pick X" recommendation (that belongs in `narrative/`).
9. **Rotate the baton** per the checklist below.

## Acceptance criteria (don't hand off until all true)

- Every load-bearing (`blocker`/`must`) cell for each assigned candidate has at least one graded evidence row with a working URL, or a recorded reason it is unknown.
- Every row's cell_id/tier/strength/bearing was checked against the source by a critic (not a finder); verdict recorded in the changelog entry.
- `vault-tool research verify` ran; every `quote_missing`/`dead` row is resolved.
- `vault-tool research check` reports zero errors.
- SYNTHESIS.md ranking matches the `vault-tool research score` output.

## Sourcing notes (accumulate these, they compound)

- (none yet; record paywalls, bot-blocks, and reliable primary sources per candidate as you find them)

## Before you finish: rotate the baton

1. Move your candidates into the **Changelog** below (date, pass #, evidence id range, critic verdict, any rubric changes).
2. **Rewrite the "Your assignment" section** above: bump the pass number, pull the next candidates, and state which cells are thin (from `vault-tool research score` `evidence_gaps`).
3. **Every 3rd pass:** audit the full grid against the rubric (re-grade drifted rows in place; re-confirm weights and tiers; re-run the pairwise check on the leaders).

---

## Changelog

- **Seeded ({{DATE}}):** Topic spun up from the research plugin templates (CSV store scaffolded, candidates and criteria seeded). No passes run yet.

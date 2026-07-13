# HANDOFF: {{TOPIC_TITLE}}

A rolling baton. Each session works **one batch of claims**, updates the data CSVs, then **rewrites the "Your assignment" section for the next session** and appends to the changelog. Read `CLAUDE.md` first; it has the framework, scope, and certainty model. This doc is the task queue, not a re-explanation.

**Mutability rule:** only the "Your assignment" section is rewriteable. The Changelog and Sourcing notes are append-only: add to them, never tidy or summarize.

---

## Your assignment (Pass 1)

Verify these **claims** (top of the queue):

1. {{CLAIM_1}}
2. {{CLAIM_2}}
3. {{CLAIM_3}}

Goal for each: evidence on both sides where it exists, graded by source tier and strength, captured verbatim with working URLs. Pass 1 establishes each claim's first contact with the sources; expect to sharpen claim wording as you go, and note every change in the changelog.

**Priorities:** all claims are untested at Pass 1; spread effort. Watch for a claim that turns out to conflate two testable statements (split it).

---

## How to do it

All files are in this topic folder. The `data/` CSVs are the source of truth.

1. **Search**, claim by claim, spawning one finder agent per claim with `FINDER-PROMPT.md` (fill the placeholders; don't improvise the prompt: edit the file, bump its version, add a changelog note if it must evolve). Check the **Sourcing notes** below first. Search-first; don't assert from memory.
2. **Critic check** before logging: one critic agent (distinct from the finders) re-checks each row's `bearing`, `source_tier`, and `strength` against the actual source, and confirms or rejects every finder-claimed refutation. Guard the grading against inflation (a listicle graded `primary`) and against length or self-preference bias in the sources. No row logs with an unconfirmed grade. Adjudicate its verdicts yourself; record the verdict in your changelog entry.
3. **Append to `data/evidence.csv`**, one row per piece of evidence. Columns:
   `evidence_id, pass, date_captured, claim_id, source_tier, strength, bearing, quote, source_type, source_url, published_date, notes`
   - Continue evidence ids from the last used (start at **E001**).
   - **Verbatim capture** into `quote`; don't translate into our jargon.
   - Retire a bad row by setting `claim_id` to `VOID`; supersede a changed source with a newer-dated row.
4. **Run `vault-tool research verify`**: it fetches every cited URL and confirms the quote is on the page (Wayback fallback), writing verdicts to `data/citations.csv`. Resolve every `quote_missing` and `dead` row in `needs_attention` (fix the quote from the source, or `VOID` the row) before the gate. `unfetchable` (bot-blocked or non-textual) is acceptable when the evidence is independently search-confirmed.
5. **Gate:** run `vault-tool research check`; zero errors before anything else proceeds.
6. **Score:** run `vault-tool research score` and read the per-claim certainty table. The scorer has already excluded `quote_missing` rows and downgraded unverified ones via `citations.csv`.
7. **Refute the load-bearing claims:** for each claim in a **top band** (`confident`/`established`), spawn one fresh-context skeptic (no stake in the existing evidence) to hunt refuting primary sources and newer information that supersedes the finding. Treat what it returns like finder output: the critic confirms each contradiction, and a confirmed one becomes a normal `refutes` row applied centrally and verified in step 4. Re-run `vault-tool research score` after applying any `refutes` rows. A claim that cannot be refuted earns its band.
8. **Re-sync `SYNTHESIS.md`:** its verdict table must match `vault-tool research score`. Synthesis only: no verbatim quotes or URLs (those stay in `data/`), no prescriptions or untraceable claims (those belong in `narrative/`).
9. **Rotate the baton** per the checklist below.

## Acceptance criteria (don't hand off until all true)

- 3 or more evidence rows per assigned claim (both bearings where they exist), each with a working source URL and a verbatim quote.
- Every row's tier/strength/bearing was checked against the source by a critic (not a finder); verdict recorded in the changelog entry.
- `vault-tool research verify` ran; every `quote_missing`/`dead` row is resolved.
- `vault-tool research check` reports zero errors.
- SYNTHESIS.md verdict table matches the `vault-tool research score` output.

## Sourcing notes (accumulate these, they compound)

- (none yet; record paywalls, bot-blocks, reliable primary sources, and superseding authorities as you find them)

## Before you finish: rotate the baton

1. Move your claims into the **Changelog** below (date, pass #, evidence id range, critic verdict, any claim splits).
2. **Rewrite the "Your assignment" section** above for the next session: bump the pass number, pull the next batch of claims, and state which claims are thinly sourced.
3. **Every 3rd pass:** audit the full evidence log against the claim wording (re-grade drifted rows in place; re-confirm which claims are still in scope).

---

## Changelog

- **Seeded ({{DATE}}):** Topic spun up from the research plugin templates (CSV store scaffolded, claims seeded). No passes run yet.

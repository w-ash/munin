# HANDOFF: {{TOPIC_TITLE}}

A rolling baton. Each session works **one batch of factors**, updates the data CSVs, then **rewrites the "Your assignment" section for the next session** and appends to the changelog. Read `CLAUDE.md` first; it has the target, the decomposition, and the propagation model. This doc is the task queue, not a re-explanation.

**Mutability rule:** only the "Your assignment" section is rewriteable. The Changelog and Sourcing notes are append-only: add to them, never tidy or summarize.

---

## Your assignment (Pass 1)

Size these **factors** (top of the queue):

1. {{FACTOR_1}}
2. {{FACTOR_2}}
3. {{FACTOR_3}}

Goal for each: a defensible low/high 90% interval (and a mid where a central source supports one), each bound cited. Pass 1 establishes the decomposition's first contact with the sources; expect to refine which factors the target breaks into, and note every change in the changelog.

**Priorities:** first confirm the decomposition is sound (factors independent, they multiply/add to the target with no double-counting); then size the factor the estimate is most sensitive to (the widest range).

---

## How to do it

All files are in this topic folder. The `data/` CSVs are the source of truth.

1. **Search**, factor by factor, spawning one finder agent per factor with `FINDER-PROMPT.md` (fill the placeholders; don't improvise the prompt: edit the file, bump its version, add a changelog note if it must evolve). Check the **Sourcing notes** below first. Search-first; don't assert a number from memory.
2. **Critic check** before logging: one critic agent (distinct from the finders) sanity-checks each factor's range against its cited sources (is the low/high defensible, are the units and date right?) and checks the decomposition for double-counting and independence violations. No factor logs with an unconfirmed range. Adjudicate its verdicts yourself; record the verdict in your changelog entry.
3. **Append to the CSVs.** Record each factor in `data/factors.csv` (`factor_id, name, op, low, mid, high, distribution, notes`), continuing factor ids from the last used (start at **F001**); pick `op` to match how the factor enters the target (`mul`/`div` for a product term, `add`/`sub` to start a new term). Add one `data/evidence.csv` row per sourced bound, keyed by `factor_id`:
   `evidence_id, pass, date_captured, factor_id, quote, source_type, source_url, published_date, notes`
   - **Choosing the path:** if every factor combines by `mul`/`div`, the scorer propagates the product **analytically** (exact). Any `add`/`sub` factor (e.g. summing segments) switches it to seeded **Monte Carlo**. Keep the decomposition as a pure product when you can; reach for sums only when the target genuinely is a sum of sub-products.
   - **Verbatim capture** into `quote`, with units and date; retire a bad row by setting `factor_id` to `VOID`; supersede a changed source with a newer-dated row.
4. **Run `vault-tool research verify`**: it fetches every cited URL and confirms the quote is on the page (Wayback fallback), writing verdicts to `data/citations.csv`. Resolve every `quote_missing` and `dead` row before the gate.
5. **Gate:** run `vault-tool research check`; zero errors before anything else proceeds.
6. **Score:** run `vault-tool research score` and read the target median, the confidence interval, the propagation method used, and the **dominant-uncertainty** factor (the largest share of the total log-variance).
7. **Refute the estimate:** the estimate leans on its widest factor, so attack that. Spawn one fresh-context skeptic (no stake in the existing ranges) told to find sources that push the dominant-uncertainty factor's range wider or shift its center, and to challenge the largest-magnitude factor. Treat what it returns like finder output: the critic confirms each revision, applied centrally (step 3) and verified (step 4). Re-run `vault-tool research score` after applying changes; a factor whose range survives attack earns its width.
8. **Re-sync `SYNTHESIS.md`:** its factor table and the target interval must match `vault-tool research score`. Synthesis only: no verbatim quotes or URLs (those stay in `data/`), no prescriptions or untraceable claims (those belong in `narrative/`).
9. **Rotate the baton** per the checklist below.

## Acceptance criteria (don't hand off until all true)

- Every assigned factor has a low/high 90% interval, each bound cited to a working source URL with a verbatim quote (and the date).
- The decomposition was checked for independence and double-counting by a critic (not a finder); verdict recorded in the changelog entry.
- `vault-tool research verify` ran; every `quote_missing`/`dead` row is resolved.
- `vault-tool research check` reports zero errors.
- SYNTHESIS.md factor table and target interval match the `vault-tool research score` output.

## Sourcing notes (accumulate these, they compound)

- (none yet; record authoritative statistical sources, unit/currency conventions, and figures prone to staleness as you find them)

## Before you finish: rotate the baton

1. Move your factors into the **Changelog** below (date, pass #, evidence id range, critic verdict, any decomposition changes).
2. **Rewrite the "Your assignment" section** above for the next session: bump the pass number, pull the next factors, and name the current dominant-uncertainty factor as the priority.
3. **Every 3rd pass:** audit the decomposition end to end (still independent? still sums/multiplies to the target?) and re-verify factors resting on stale figures.

---

## Changelog

- **Seeded ({{DATE}}):** Topic spun up from the research plugin templates (CSV store scaffolded, target and factors seeded). No passes run yet.

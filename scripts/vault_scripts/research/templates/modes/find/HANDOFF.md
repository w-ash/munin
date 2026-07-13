# HANDOFF: {{TOPIC_TITLE}}

A rolling baton. Each session works **one slice of the frame**, updates the data CSVs, then **rewrites the "Your assignment" section for the next session** and appends to the changelog. Read `CLAUDE.md` first; it has the frame, scope, and coverage model. This doc is the task queue, not a re-explanation.

**Mutability rule:** only the "Your assignment" section is rewriteable. The Changelog and Sourcing notes are append-only: add to them, never tidy or summarize.

---

## Your assignment (Pass 1)

Enumerate these **slices** of the frame (top of the queue):

1. {{SLICE_1}}
2. {{SLICE_2}}
3. {{SLICE_3}}

Goal for each slice: every entity that matches the frame, each with its required attributes filled and cited. Pass 1 establishes the roster's first contact with the frame; expect to sharpen the frame wording and the attribute set as you go, and note every change in the changelog.

**Priorities:** breadth first (get the roster near-complete) before depth (backfilling optional attributes). Flag any slice you could not exhaust.

---

## How to do it

All files are in this topic folder. The `data/` CSVs are the source of truth.

1. **Search**, slice by slice, spawning one finder agent per slice with `FINDER-PROMPT.md` (fill the placeholders; don't improvise the prompt: edit the file, bump its version, add a changelog note if it must evolve). Check the **Sourcing notes** below first. Search-first; don't assert from memory.
2. **Critic check** before logging: one critic agent (distinct from the finders) confirms each entity actually belongs in the frame (no false members inflating recall) and re-checks each field value against its cited source (a URL that resolves to the wrong entity fails). No cell logs with an unconfirmed source. Adjudicate its verdicts yourself; record the verdict in your changelog entry.
3. **Append to the CSVs.** Add each new entity to `data/entities.csv` (`entity_id, name, in_frame, <attribute columns>`), continuing entity ids from the last used (start at **E001**). Add one `data/evidence.csv` row per sourced field, keyed by `cell_id` = `<entity_id>--<attribute_id>`:
   `evidence_id, pass, date_captured, cell_id, quote, source_type, source_url, published_date, notes`
   - **Verbatim capture** into `quote`; don't translate into our jargon.
   - Leave a cell blank when unsourced; retire a wrong row by setting `cell_id` (or an entity's membership) to `VOID`; supersede a changed source with a newer-dated row.
4. **Run `vault-tool research verify`**: it fetches every cited URL and confirms the quote is on the page (Wayback fallback), writing verdicts to `data/citations.csv`. Resolve every `quote_missing` and `dead` row in `needs_attention` (fix the quote from the source, or `VOID` the row) before the gate. `unfetchable` (bot-blocked or non-textual) is acceptable when the field is independently search-confirmed.
5. **Gate:** run `vault-tool research check`; zero errors before anything else proceeds.
6. **Score:** run `vault-tool research score` and read the coverage table: recall against the frame (or the saturation curve when the size is unknown), per-attribute fill and verified rates, and the thin entities missing a required field.
7. **Refute the coverage claim:** the roster leans on being *complete*, so attack that. Spawn one fresh-context skeptic (no stake in the existing roster) told to find entities in the frame that the roster is missing, and to challenge any in-frame membership that looks like a false positive. Treat what it returns like finder output: the critic confirms each addition or removal, and confirmed ones are applied centrally (step 3) and verified (step 4). Re-run `vault-tool research score` after applying changes.
8. **Re-sync `SYNTHESIS.md`:** its coverage table must match `vault-tool research score`. Synthesis only: no verbatim quotes or URLs (those stay in `data/`), no prescriptions or untraceable claims (those belong in `narrative/`).
9. **Rotate the baton** per the checklist below.

## Acceptance criteria (don't hand off until all true)

- Every assigned slice enumerated, with its coverage gap stated (which entities are still expected-missing).
- Every in-frame entity has its `required` attributes filled, each cell traced to a working source URL and a verbatim quote.
- Every field value was checked against its source by a critic (not a finder); verdict recorded in the changelog entry.
- `vault-tool research verify` ran; every `quote_missing`/`dead` row is resolved.
- `vault-tool research check` reports zero errors.
- SYNTHESIS.md coverage table matches the `vault-tool research score` output.

## Sourcing notes (accumulate these, they compound)

- (none yet; record paywalls, bot-blocks, authoritative registries, and profile-URL quirks as you find them)

## Before you finish: rotate the baton

1. Move your slices into the **Changelog** below (date, pass #, entity id range, critic verdict, any frame changes).
2. **Rewrite the "Your assignment" section** above for the next session: bump the pass number, pull the next slices, and state which slices are still thin.
3. **Every 3rd pass:** audit the roster against the frame (re-confirm memberships, re-verify drifted cells, check the saturation curve for whether the frame is exhausted).

---

## Changelog

- **Seeded ({{DATE}}):** Topic spun up from the research plugin templates (CSV store scaffolded, frame and attributes seeded). No passes run yet.

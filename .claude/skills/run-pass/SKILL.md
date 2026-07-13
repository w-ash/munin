---
name: run-pass
description: Execute the next research pass on an evidence-based research topic. Use when asked to run a pass, pick up the baton, continue the research, or work the next batch of units in a directory with a research.toml.
user_invocable: true
---

# Run a Research Pass

The topic's `HANDOFF.md` is the baton: its "Your assignment" section names the batch and priorities, and its "How to do it" section is the canonical, mode-specific step list. This skill adds the agent mechanics around it. Read the topic's `CLAUDE.md`, `HANDOFF.md`, and `.claude/rules/` first. Work from the topic directory (the one with `research.toml`); the CLI is `scripts/vault-tool research`, with `--dir <topic>` when you are not inside it.

## Mode first

Read `mode` from `research.toml`; it decides the store schema, the finder prompt, the apply rules, and what "load-bearing" means. The steps below are the shared shape; the topic's own `FINDER-PROMPT.md` and `.claude/rules/evidence.md` carry the mode's specifics, so follow those over any map-flavored habit.

| mode | batch unit | finders gather | scored by |
|---|---|---|---|
| `map` | units | findings tagged to categories (`-div` for divergence) | breadth confidence per category |
| `verify` | claims | source-graded evidence per claim (tier/strength/bearing) | source-weighted certainty per claim |
| `rank` | candidates | source-graded evidence per grid cell (`<candidate>--<criterion>`) | rubric fit per candidate, blocker-gated |
| `find` | frame slices | attribute values per cell (`<entity>--<attribute>`), each citable | recall over the frame + per-field verification |
| `estimate` | factors | a sourced value + 90% range per factor | target magnitude with a propagated interval |

## Procedure

1. **Finders:** spawn one agent per batch item (plain parallel Agent calls, `sonnet`-class), each prompted from the topic's `FINDER-PROMPT.md` with placeholders filled from the HANDOFF assignment. Include relevant HANDOFF sourcing notes. Never improvise the prompt; if it must evolve, edit the file, bump its version, and note it in the changelog.
2. **Critic:** one distinct agent (`sonnet`-class) reviews all candidate findings for the judgment no tool can make. For `map` that is each `category_id` against the boundary definitions and every claimed `-div`; for `verify`/`rank` it is each row's `source_tier`, `strength`, and `bearing` against the actual source, plus every claimed refutation; for `find` it is whether each entity truly belongs in the frame (no false members inflating recall) and whether each field value matches its cited source (a URL that resolves to the wrong entity fails); for `estimate` it is whether each factor's low/high range is defensible from its sources and whether the decomposition double-counts or breaks independence. Guard graded modes against grade inflation and against length / self-preference bias in the sources. Nothing contested logs unconfirmed. Adjudicate its verdicts yourself: the critic advises, the main loop decides.
3. **Apply centrally:** append the adjudicated rows to `data/` yourself, in one place, after adjudication. Agents never write the store. Follow the store conventions in the topic's `.claude/rules/evidence.md` (verbatim capture, the mode's id and column shape, VOID/supersede handling, continue ids).
4. **Verify citations (mechanical):** run `scripts/vault-tool research verify`. It fetches every cited URL and confirms the verbatim quote is on the page (Wayback fallback for dead links), and for `verify`/`rank` it **writes the verdicts to `data/citations.csv`** so the scorer can exclude `quote_missing` rows and downgrade unverified ones. Resolve each `quote_missing` and `dead` row in `needs_attention` before the gate: fix the quote from the source, or VOID the row. `unfetchable` (bot-blocked or non-textual) is acceptable when the finding is independently search-confirmed.
5. **Gate:** run `scripts/vault-tool research check`; zero errors before anything else proceeds. Read its warnings too.
6. **Score:** run `scripts/vault-tool research score` (the mode-dispatched scorer; `scripts/vault-tool research status` is a back-compat alias that still scores map topics). Read the table: category confidence (`map`), per-claim certainty (`verify`), candidate fit ranking (`rank`), recall + per-field verification (`find`), or the target median, interval, and dominant-uncertainty factor (`estimate`).
7. **Refute the load-bearing claims:** attack whatever the report leans on, per mode: **High-tier categories** (`map`), **top-band claims** (`confident`/`established`, `verify`), **the leading and closest candidates' blocker/must cells** (`rank`), **the frame's completeness and any shaky in-frame membership** (`find`: hunt for entities the roster is missing and false members inflating recall), or **the dominant-uncertainty and largest-magnitude factors** (`estimate`: push the widest factor's range or shift its center). Spawn one fresh-context skeptic (`sonnet`-class, no stake in the existing findings) told to search for contradicting primary sources, counter-examples, and newer information that supersedes the finding. For `rank`, also run a small **pairwise** comparison of the leaders with 2-3 independent judges (or temperature variants) and report order-dependent disagreement rather than averaging it. Treat what they return like finder output: the critic (step 2) confirms each contradiction, and a confirmed one becomes a normal counter-row (`map`: `<id>-div`; `verify`/`rank`: a `refutes` row; `find`: an added/removed entity or corrected cell; `estimate`: a revised factor range) applied centrally (step 3) and verified (step 4). Bound the cost: a few per pass at most. Re-run `scripts/vault-tool research check` and `scripts/vault-tool research score` after applying any counter-rows. The scorer already reflects confirmed counter-evidence, so a finding that cannot be refuted earns its standing.
8. **Re-sync `SYNTHESIS.md`:** its tables must match the `research score` output. Synthesis only: no verbatim quotes or URLs, no build/design/sell prescriptions or any claim not traceable to `data/` (those belong in `narrative/`, framed as possible approaches). Keep the neutral voice from the topic CLAUDE.md.
9. **Land the vault note.** The topic directory is the working store; the durable, vault-facing record is a polished note. After `SYNTHESIS.md` is re-synced, write or refresh one markdown note per the trackers framework (`.claude/rules/trackers.md`), placed where the requesting context dictates:
   - Research feeding a project decision: the project's folder, or `Meta/` when the subject is vault structure or conventions themselves.
   - Trip research: the trip's folder (`Travel/<Trip>/References/` when it exists).
   - Freestanding exploration: `Ideas/`.

   Note requirements:
   - `created: "YYYY-MM-DD"` frontmatter; follow the destination folder's tag conventions (e.g. `meta` in `Meta/`).
   - Structure: a one-paragraph headline verdict; findings grouped by confidence band (or the ranking / roster / interval, per mode), each stating its certainty and citing its sources; a refuted / low-confidence section (what verification drove down); caveats; open questions; and a sources list. The certainty numbers and bands come from `scripts/vault-tool research score` (and `rank`), never by hand; keep the refuted section, it is decision input, not noise.
   - Prose per `.claude/rules/writing.md` (plain punctuation, no em dashes).
   - Wikilink the note from whatever prompted the research, and link back. The note is the record; the topic directory and its CSVs stay outside the vault.
10. **Rotate the baton** per HANDOFF's checklist: append the changelog entry (with the critic verdict and any workflow run ids), rewrite the assignment for the next pass, update the queue, and (for `map`) append the next batch's canonical names to `research.toml` `units`. Every 3rd pass: run the audit the mode's HANDOFF describes.
11. **Share (optional):** `scripts/vault-tool research sync` pushes any topic's store to its Google Sheet, with the mode's computed block joined onto its core tab (map: confidence on Taxonomy; verify: certainty on Claims; rank: fit on Candidates; find: coverage rates on Attributes; estimate: log-space parameters on Factors) and a per-mode model doc tab (see the `share-research` skill).

## Checks before declaring done

All HANDOFF acceptance criteria true, `research check` clean, SYNTHESIS.md tables match `research score`, the vault note landed and wikilinked, baton rotated.

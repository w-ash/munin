---
name: new-research
description: Spin up a new evidence-based research topic and seed it. Use when asked to start a research topic, spin up a study, set up an evidence-based research project, standardize research on a question, or begin a deep/scored/ranked research effort. All research goes through this harness.
user_invocable: true
argument-hint: "<slug> \"Topic Title\""
---

# New Research Topic

Scaffold a topic directory with `vault-tool research`, then seed it with the user
in a short interview. A topic is not ready for Pass 1 until every seeding
placeholder is filled. The command is `scripts/vault-tool research` (provided by
this repo; no install needed).

## Where topics live

A topic directory is a working store (append-only `data/*.csv`, a regenerated
`SYNTHESIS.md`, hand-authored `narrative/`), so it lives **outside iCloud**, never
inside the vault: the default research home is `~/.local/share/vault-research/`.
The durable, vault-facing record is the polished note the `run-pass` skill lands
per the trackers framework, not the topic directory.

## Procedure

1. **Classify the mode.** Before scaffolding, pin down the research shape. Ask 2-3
   of these (only what the request doesn't already answer):
   - **Question shape**: how does this space break down (`map`) / are these claims
     true (`verify`) / which candidate is best (`rank`) / get every entity matching
     a filter, with attributes (`find`) / how big or how much, now (`estimate`)?
   - **What "done" looks like**: a category taxonomy, verdicts with certainty, a
     ranking, a complete roster, or a number with a range?
   - **Sampling vs census**: sample a population for patterns (`map`) or enumerate a
     bounded frame exhaustively (`find`)?

   Propose one mode with a one-line rationale and get the user's sign-off. The mode
   picks the store schema and scorer; it is recorded in `research.toml` and revisable
   at an audit, so classify for the question as posed, not for every future
   direction. All five modes are implemented. A "why did X happen" diagnosis is a
   `verify` topic with the candidate causes framed as competing claims.

2. **Scaffold.** Resolve the slug (kebab-case) and title from `$ARGUMENTS`, confirm
   the destination (default: the research home above), and run:

   ```bash
   scripts/vault-tool research new <slug> "Topic Title" \
     --dest ~/.local/share/vault-research --mode <mode>
   ```

   This creates the topic with templates (CLAUDE.md, HANDOFF.md, FINDER-PROMPT.md,
   SYNTHESIS.md, `narrative/`, `.claude/rules/`), header-only `data/` CSVs, and
   `research.toml` with the mode recorded.

3. **Interview.** Gather from the user, asking only for what the request didn't
   already provide. The first three are shared; the last block depends on the mode.
   - **Research question**: the single question the evidence must answer.
   - **Guiding lens**: the angle that decides which findings matter.
   - **Audience** for the synthesis, and which narrative docs to plan (see
     `narrative/README.md`).
   - **Scope guards**: what's explicitly out.
   - Then, per mode:
     - `map`: the **unit of analysis** (singular noun) and the **ordered queue** of
       units; a **best-guess taxonomy** (categories with a one-line definition and
       explicit boundary each; expect a pass-2/3 refactor); a **watch list** of
       material below the promotion bar.
     - `verify`: the **claims** under test, each a single falsifiable statement, and
       which are load-bearing for the question.
     - `rank`: the **candidates** being compared, and the **rubric** (criteria with a
       weight and a `blocker`/`must`/`should`/`nice` tier each).
     - `find`: the **frame** (the named, bounded population to enumerate) and, if it
       is a known-size set, its **expected_count**; the **attributes** to extract per
       entity (which are `required`); and the first slices of the frame to work.
     - `estimate`: the **target quantity** to size, and its **decomposition** into
       factors (each with a low/high 90% range and how it combines: `mul`/`div` for a
       product, `add`/`sub` for a summed term), kept independent to avoid
       double-counting.

4. **Seed the files.**
   - Fill every seeding `{{...}}` placeholder in `CLAUDE.md`, `HANDOFF.md`, and
     `FINDER-PROMPT.md` (research question, lens, audience, scope, and the mode's
     list: taxonomy/units, claims, candidates+criteria, the frame+attributes, or the
     target+factors). Leave the per-spawn placeholders the FINDER-PROMPT fills at
     finder time (e.g. `{{CLAIM_ID}}`, `{{SLICE}}`, `{{FACTOR_ID}}`).
   - Seed the mode's core CSVs (leave synthesis/computed fields empty): `map` -> one
     row per category in `data/taxonomy.csv`; `verify` -> one row per claim in
     `data/claims.csv`; `rank` -> `data/candidates.csv` and `data/criteria.csv` (set
     each criterion's `weight` and `tier`); `find` -> one row per field in
     `data/attributes.csv` (mark which are `required`), with `data/entities.csv`
     seeded only where entities are already known; `estimate` -> one row per factor
     in `data/factors.csv` (set `op`, `low`/`high`, and `mid` where known).
   - In `research.toml`: `map` sets `unit_noun`, `category_prefix`, and the Pass 1
     `units`, tuning `[confidence]` only for a small unit population; `verify`/`rank`
     tune `[verify]` (and `[rank] blocker_threshold`) only with reason; `find` sets
     `[find] frame` (and `expected_count` when the frame is a known-size set);
     `estimate` tunes `[estimate]` (`ci`, and the Monte Carlo `mc_samples`/`mc_seed`)
     only with reason.
   - If sharing is wanted now, have the user create a blank Google Sheet and set
     `[sheets] sheet_id` (and `[sheets] auth`; see the `share-research` skill).

5. **Verify.** Run `scripts/vault-tool research check` (must be clean) and
   `grep -rn "{{" <topic-dir> --include="*.md"` (the only hits allowed are the
   FINDER-PROMPT's per-spawn placeholders, filled per finder at pass time; every
   seeding placeholder must be gone). Report the topic path and the next step: run
   Pass 1 with the `run-pass` skill.

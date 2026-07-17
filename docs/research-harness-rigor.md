# Research Harness Rigor (verification should be enforced, not optional)

> Brief for a future agent. During a real research task, the evidence-research harness was used in a way that silently dropped its core value (verified, source-traceable claims), and nothing in the tooling stopped it. This note explains what happened and offers some starting hypotheses, but it deliberately does NOT prescribe the fix. The agent who takes this on should research best practices, study our systems at large (munin, aesc, and how they interlock), and come up with its own diagnosis and plan. The hypotheses below are hunches from a single incident, not a design.

## What happened (the concrete failure)

Running the `supplement-timing` study, the harness was set up correctly: `new-research` scaffolded and seeded the topic, and finder agents gathered evidence. Then the run **skipped the middle of `run-pass`**. Instead of appending the finder output to the evidence store, running `verify`, `check`, and `score`, and rendering a vault note from the verified store, the finder conclusions were **hand-transcribed** into vault notes with a single hand-typed source link each. `evidence.csv` stayed at 0 rows. Nothing was citation-checked.

When `verify` was finally run retroactively (after the user caught it), the honest picture appeared: of 104 citations, **18 failed**, 13 where the page loaded but the exact quote was not on it, and 5 dead links, mostly bot-blocked interaction-checker and aggregator pages (drugs.com, Examine) that had been quoted from search-result snippets rather than fetched pages. None of that was visible in the vault until the check ran.

Net: the vault briefly held hand-authored claims and unverified links, which is exactly what the harness exists to prevent. The failure was a process shortcut, made possible because the tooling does not enforce the steps that matter.

## Why it was possible (observations, not conclusions)

- **The rigor is prose, not a gate.** `run-pass` lists acceptance criteria ("don't hand off until verify ran, check clean"), but nothing mechanical blocks writing a polished vault note while the store is empty and unverified.
- **The canonical steps are manual.** "Append to the store" and "render the durable note" are done by hand, so under time pressure they get skipped or improvised. In this incident they were reconstructed after the fact with two throwaway scripts (`populate_store.py` to ingest the finder JSON, `gen_timing_study.py` to render the note from the store). That those scripts had to exist at all is a strong hint about what commands are missing.
- **The finder prompt allowed snippet-sourced quotes.** Most unverifiable citations came from quoting a search snippet of a page that never actually loaded. There was no rule forcing "quote only what you fetched."
- **No rule binds vault notes to the store.** The store has internal synthesis discipline, but nothing requires the vault-facing note to be a projection of verified evidence, or requires unverified cells to be marked rather than presented as settled.

## Hard constraint: the tool and the research data must stay separate

munin is the tool that drives research, and it is pushed to GitHub. Research files (topic working stores, `evidence.csv` / `citations.csv` / `entities.csv`, `research.toml`, and any generated artifacts) must NEVER live in munin. This is a firm requirement, and a major part of the reorganization.

Current state (checked 2026-07-12): the principle already holds for data, but only by convention, not by enforcement.

- Research data lives outside munin, in `~/.local/share/vault-research/` (topics: `berkeley-offer-model`, `supplement-timing`, `supplements-regimen`). Nothing research-related is committed in munin except the tool's own `templates/`.
- But nothing enforces it: `research new --dest` can point a topic anywhere, including inside munin or any git working tree; there is no gitignore or tool-level guard; and the tool/data boundary is undocumented and unchecked.

The reorganization must make the separation explicit and enforced: the tool refuses to create or write a research store inside its own repo (or any repo it should not pollute), the data home is a deliberate and documented location, and the boundary is verifiable. A related but separate question the agent should surface (not decide): a lot of aesc-specific domain config (rules, skills) also lives in munin via the symlink, and whether that belongs in the tool repo is worth raising, though it is beyond "research files" and is the user's call.

## Possible directions (starting hypotheses, to be pressure-tested, NOT adopted as-is)

- A **store → verify → render pipeline** where the durable vault note is generated from the verified store, never hand-written. Possibly: a `research ingest` (finder JSON into `evidence.csv`), a `research render` (per-mode note generator), and a strict gate (`research land` or `check --strict`) that refuses on an empty store, missing `citations.csv`, or a verified-rate below a threshold.
- A **rule** (in the research/trackers rules) that research reaches the vault only via that pipeline, and that unverified cells are marked, not hidden.
- **Finder-prompt hardening:** quote only from a page actually fetched; if blocked, leave the cell unquoted.
- **Verification status in the landed-note template by default**, so a reader always sees which claims are checked.

Treat these as leads. The right answer might be simpler, might live in a different layer (CLI vs skill vs rule vs hook), and should avoid over-engineering.

## What the agent should actually do

Do not just implement the hypotheses. First research, then plan:

1. **Best practices.** How do rigorous systems make documents verifiable by construction, enforce provenance, and gate on citation checks? What do reproducible-research and evidence-pipeline tools do about dead links, snippet-sourcing, and drift between a claim and its source?
2. **Our systems at large.** Study the munin research harness end to end: the `vault-tool research` CLI (`scripts/vault_scripts/research/`), the `new-research` / `run-pass` / `share-research` skills, the per-topic and global rules, the topic-directory contract, and how a landed note gets into aesc. Study how this relates to the two-tier Trackers framework (`Meta/Trackers.md`, `.claude/rules/trackers.md`) and the Eir canonical-files + query-cache pattern. Decide where enforcement belongs and what is minimal.
3. **Form its own plan.** Root-cause diagnosis, the design (commands, rules, prompt changes, and how vault notes reference verified evidence), alternatives with a recommendation, and a rollout that prevents recurrence.

## Where to look (incident artifacts)

- The topic and its now-populated, verified store: `~/.local/share/vault-research/supplement-timing/` (`data/entities.csv`, `data/evidence.csv`, `data/citations.csv`).
- The vault surface it produced: `Health/Supplements/Timing Study.md` (rendered from the store, with per-claim verification marks) and the `entries/*.md` notes.
- The throwaway ingest/render scripts (the shape of the missing commands): in this session's scratchpad, `supplements/populate_store.py` and `supplements/gen_timing_study.py`.
- munin: `scripts/vault-tool research`, `scripts/vault_scripts/research/` (incl. `certainty.py`, `store.py`, `cli.py`, `templates/`), the research skills and rules.

## Deliverable

A design doc plus recommendation for the user to approve before building: the root cause, the proposed enforcement (with alternatives and a pick), the concrete changes across munin (CLI / skills / rules / finder prompt) and how aesc notes reference verified evidence, and a rollout plan. Build only after approval.

## Non-goals

- Not to re-run the supplement study (that is being fixed separately).
- Keep to the vault's doctrines: Trackers tiers, no capture chores, plain-punctuation writing (`.claude/rules/writing.md`).

## Note on placement

This brief lives in the aesc vault for review, but the work is mostly in munin (the tooling). Moving it into munin's own backlog may be the better home once the agent scopes it.

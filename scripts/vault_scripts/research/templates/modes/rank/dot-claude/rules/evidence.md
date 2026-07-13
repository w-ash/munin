# Evidence Store Rules (rank)

The `data/` CSVs are the database: `candidates.csv`, `criteria.csv` (the weighted rubric), and append-only `evidence.csv` (source-graded rows attached to grid cells), plus any topic-specific extras. If docs disagree with the CSVs, the CSVs win. Fit is never stored anywhere; the `research` CLI computes it from the evidence on every run (`vault-tool research score`).

## Scope (don't drift)

Unit of analysis: **a candidate**. In scope: {{IN_SCOPE}}. Explicitly OUT: {{OUT_OF_SCOPE}}.

**The rubric is revisable, not open-ended.** A pass may re-weight a criterion, promote one to `blocker`, or add a criterion the comparison turns out to need, but it does not invent candidates. Record every change in the HANDOFF changelog. Each criterion is a single dimension a candidate can be scored on from evidence.

## Scoring model (per-cell certainty, rolled up)

Each grid cell (`<candidate_id>--<criterion_id>`) is a claim scored by the same decibans engine as `verify`: source tier (primary > community > secondary > weak) x strength (strong / moderate / weak), signed by bearing (supports / refutes), with same-domain diminishing returns and the no-primary ceiling. A cell with no evidence sits at the prior (50%): unknown, not failing.

The rollup into a per-candidate fit score:

- **fit** = weight-normalized mean of the candidate's criterion certainties (0-100).
- **Criterion tier** sets the gating role: `blocker` (a hard requirement), `must` / `should` / `nice` (weighted preferences). `blocker` and `must` are the **load-bearing** set.
- **Blocker gating:** a `blocker` scoring below `research.toml` `[rank] blocker_threshold` (default 50%) marks the candidate **blocked** and caps its fit at that cell's certainty. A blocked candidate never outranks a clean one, regardless of fit.
- **Weakest link:** `least_resolved` names the load-bearing criterion nearest 50% (the natural re-research target); `evidence_gaps` lists load-bearing cells resting on fewer than 2 sources.

## Conventions

- **Append-only evidence**, with carve-outs: set `cell_id` to `VOID` to retire a bad row; supersede a changed source with a newer-dated row.
- **Capture verbatim** into `quote`; don't translate the source's wording.
- **Evidence-backed only**; no invented findings, no guessed URLs. Every row needs a real `source_url` and a `quote`, and a `cell_id` that resolves to a real candidate x criterion.
- **Grade honestly:** `source_tier` and `strength` are the scorer's only inputs besides bearing; the citation pass and the no-primary ceiling guard against inflation.
- **`vault-tool research verify` before scoring:** it writes per-row verdicts to `data/citations.csv`; the scorer excludes `quote_missing` cells and downgrades unverified ones. Resolve `quote_missing`/`dead` rows before the gate.
- **`vault-tool research check` gates every pass:** zero errors before the baton rotates.

## Pairwise sanity check and judge bias

The rollup is pointwise (each cell scored on its own), which can miss order-dependent judgment. On the close calls near the top of the ranking, run a small **pairwise** check: ask 2-3 independent judges (or temperature variants) to compare the leading candidates head to head, and report order-dependent disagreement rather than averaging it away. Guard the per-cell judgments against verbosity/length bias (a longer source is not a stronger one) and self-preference bias alongside the position-bias the ensemble catches.

## Synthesis discipline

`SYNTHESIS.md` carries only what the evidence supports: the fit ranking, the blocking status, and the weakest cells. Keep recommendations ("pick X") and any claim not traceable to `data/` out; those belong in `narrative/`, framed as the reader's decision to make from the ranking.

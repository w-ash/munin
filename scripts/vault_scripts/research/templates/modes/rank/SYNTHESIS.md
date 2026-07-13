# {{TOPIC_TITLE}}: Synthesis

*{{RESEARCH_QUESTION}}*

*This is the synthesis plane. Verbatim quotes, per-source detail, and source URLs live in `data/` (candidates, criteria, evidence), which is the source of truth. Fit is computed by `vault-tool research score`; the tables below mirror its output.*

---

## How to read this

(Explain the rubric's shape, which criteria are load-bearing, and how the candidates differ. Written at first re-sync.)

## Ranking

| Rank | Candidate | Fit | Status | Least resolved | Evidence gaps |
|---|---|---|---|---|---|
| 1 | - | - | - | - | - |

*Fit is a weight-normalized mean of per-criterion certainties. A blocked candidate (a failing `blocker` criterion) is capped and sorts below every clean candidate regardless of fit.*

---

## Candidate detail

### (Candidate name)
(How it scores on each criterion, what blocks it if anything, its weakest load-bearing cell, and the head-to-head result against its nearest rival.)

| Criterion | Tier | Certainty | Band | Sources |
|---|---|---|---|---|
| - | - | - | - | - |

---

## Method

**Rubric (computed by `vault-tool research score`).** Each grid cell is a claim scored by source-weighted log-odds (decibans): primary > community > secondary > weak, scaled by strength and signed by bearing, with same-domain diminishing returns and a no-primary ceiling. An empty cell sits at the 50% prior. Fit is the weight-normalized mean; a `blocker` below the threshold caps and de-ranks the candidate. The leaders were compared **pairwise** by independent judges; order-dependent disagreement is reported, not averaged.

---

## Limitations

**What fit measures.** It is a consistency convention over graded sources, not automatically a calibrated score (`vault-tool research calibrate` checks per-cell certainty against human labels in `data/gold.csv` once some cells have been adjudicated), and it reflects the sourcing that was *findable* per cell. Cells still at the prior are unknowns, not neutral scores.

**Unequal evidence.** Candidates and criteria are unevenly documented in public sources; note here which cells are thin. A ranking that turns on a thin load-bearing cell deserves a re-research round before it is trusted.

**Judge bias.** Pointwise cell scores and pairwise comparisons both carry model bias (position, verbosity, self-preference); the ensemble check bounds it but does not remove it.

*Verbatim quotes, per-source detail, and all URLs: `data/`.*

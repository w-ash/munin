# {{TOPIC_TITLE}}: Synthesis

*{{RESEARCH_QUESTION}}*

*This is the synthesis plane. Verbatim quotes, per-source detail, and source URLs live in `data/` (claims, evidence), which is the source of truth. Certainty is computed by `vault-tool research score`; the table below mirrors its output.*

---

## How to read this

(Explain which claims are load-bearing for the research question and how they relate. Written at first re-sync.)

## Verdicts

| Claim | Certainty | Band | Sources | Note |
|---|---|---|---|---|
| CL1 | - | - | - | - |

*Certainty is source-weighted (decibans), not a vote count: one primary source outweighs several weak ones, and a refuting source subtracts. See the rubric below.*

---

## Claim detail

### CL1 (claim text)
(What the evidence shows for and against, the net certainty and band, which sources carry it, and any unresolved refutation.)

---

## Certainty & sourcing

**Rubric (computed by `vault-tool research score`).** Each source moves a claim by a tier-based log-odds increment (decibans): primary > community > secondary > weak, scaled by strength (strong / moderate / weak) and signed by bearing (supports / refutes). Same-domain sources diminish (1, 1/2, 1/4). A claim with no supporting primary source is capped below the top bands. Bands: **established >= 90% | confident >= 75% | likely >= 55% | tentative >= 35% | speculative >= 15% | refuted below.**

| Claim | Certainty | Band | # sources | Net decibans | Capped |
|---|---|---|---|---|---|
| CL1 | - | - | - | - | - |

**Citation status:** (how many rows verified vs quote-missing at the last `vault-tool research verify`; unverified rows were downgraded before scoring.)

---

## Limitations

**What certainty measures.** It is a consistency convention across graded sources, not automatically a calibrated probability (`vault-tool research calibrate` checks it against human labels in `data/gold.csv` once some claims have been adjudicated). It reflects the sourcing that was *findable*, which over-weights whatever publishes prominently.

**Unverified refutation.** A claim in a top band that has not drawn an active refutation pass is provisional; note here which claims are still unattacked.

**Superseded sources.** A source can be authoritative and stale. Where a claim's certainty rests on an older source, flag it and plan re-verification.

*Verbatim quotes, per-source detail, and all URLs: `data/`.*

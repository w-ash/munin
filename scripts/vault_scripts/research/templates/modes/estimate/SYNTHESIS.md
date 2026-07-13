# {{TOPIC_TITLE}}: Synthesis

*{{RESEARCH_QUESTION}}*

*This is the synthesis plane. The factor ranges, verbatim quotes, and source URLs live in `data/` (factors, evidence), which is the source of truth. The magnitude is computed by `vault-tool research score`; the tables below mirror its output.*

---

## How to read this

(Explain what is being sized and how the target decomposes. Written at first re-sync.)

## Estimate

**Target:** {{TARGET_QUANTITY}}

| | Value |
|---|---|
| Median | - |
| Interval (90% CI) | - .. - |
| Propagation | - |
| Dominant uncertainty | - |

*The interval is propagated from the factor ranges, not a guess: a pure product/quotient is exact (analytic lognormal), a decomposition with sums uses seeded Monte Carlo. The dominant-uncertainty factor carries the largest share of the spread.*

## Factors

| Factor | Op | Median | Range (90%) | Variance share |
|---|---|---|---|---|
| - | - | - | - | - |

---

## Limitations

**What the interval measures.** It propagates the *stated* factor ranges under an independence assumption. If two factors secretly move together (or double-count), the true interval is wider than shown. The estimate is a structured reasoning aid, not a measurement.

**Decomposition risk.** The result is only as sound as the decomposition: a missing factor, or one that is really two, biases the point as well as the spread.

**Staleness.** A factor can rest on an authoritative but dated figure. Where it does, flag it and plan re-sizing; present-state sizing assumes the inputs are current.

*Verbatim quotes, per-factor detail, and all URLs: `data/`.*

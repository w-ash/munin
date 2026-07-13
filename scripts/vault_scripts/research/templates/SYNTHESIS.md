# {{TOPIC_TITLE}}: Synthesis

*{{RESEARCH_QUESTION}}*

*This is the synthesis plane. Verbatim findings, per-source detail, and source URLs live in `data/` (taxonomy, evidence, sources), which is the source of truth. Confidence is computed by `vault-tool research status`; the tables below mirror its output.*

---

## How to read this

(Explain the taxonomy's shape and how the categories relate. Written at first re-sync.)

## Summary

| # | Category | What it is | Key signal | Confidence |
|---|---|---|---|---|
| C1 | - | - | - | - |

*Confidence reflects cross-unit breadth rather than depth (see rubric below).*

---

## Category profiles

### C1 (name)
(What the evidence shows, what it means for the research question, and status: which pass established it, how many units, any divergence.)

---

## Confidence & coverage

**Rubric (computed by `vault-tool research status`, falsifiable).** Confidence is driven by cross-unit breadth and can go down: `confidence = max(0%, min(95%, 10% x supporting units) - 10% x diverging units)`. Divergence subtracts after the cap, so counter-evidence never saturates: a fully capped category still loses 10% per diverging unit. A category stays **Low until seen at 5+ net units**. Tiers: **High >= 85% (9+ units) · Medium-High 65-84% (7-8) · Medium 50-64% (5-6) · Low < 50% (<= 4).** Supporting evidence caps at 95%; the last 5% needs primary validation.

| Category | Supporting units | Diverging units | Evidence rows | Confidence | Tier |
|---|---|---|---|---|---|
| C1 | - | - | - | - | - |

**Unit coverage:** (which units each pass covered; how many pending.)

**Watch-list candidates:** (categories being watched; promoted when they clear the bar in CLAUDE.md.)

---

## Limitations

**What sampling measures.** Confidence reflects what was *observable* in public sources; that is a proxy for what exists, not a census. The method over-samples whatever publishes or churns frequently and under-samples stable or private material, so a category's confidence can lag its true prevalence.

**Unevenly evidenced aspects.** Some aspects of the research question are systematically harder to observe from public sources (note here which, once known). Conclusions resting on those aspects deserve extra caution and a plan for primary validation.

**Snapshot timing.** Evidence is captured on specific dates (see the evidence log); source visibility can be seasonal or news-cycle driven, so category visibility partly reflects capture timing. Passes spread over time dilute this.

**The unit is fuzzy.** Breadth counts each unit once regardless of size, and subsidiary or component evidence rolls up to the parent unit. Unit strings are standardized against `research.toml` so the distinct-unit count stays honest.

**Definition drift.** Each pass tempts categories to absorb adjacent material, which would raise confidence by definitional creep rather than evidence. Near-misses are recorded in taxonomy notes rather than the evidence log, per-category boundary definitions guard the line, and the divergence mechanism records outright contradictions instead of quietly absorbing them.

*Evidence rows, per-source detail, and all source URLs: `data/`, mirrored to the shared Google Sheet by `vault-tool research sync`.*

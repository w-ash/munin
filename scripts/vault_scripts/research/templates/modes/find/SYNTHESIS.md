# {{TOPIC_TITLE}}: Synthesis

*{{RESEARCH_QUESTION}}*

*This is the synthesis plane. The roster rows, verbatim quotes, and source URLs live in `data/` (entities, attributes, evidence), which is the source of truth. Coverage is computed by `vault-tool research score`; the tables below mirror its output.*

---

## How to read this

(Explain the frame being enumerated and how complete the roster is. Written at first re-sync.)

## Coverage

**Frame:** {{FRAME_DEFINITION}}

| Metric | Value |
|---|---|
| Entities found | - |
| Frame size (expected) | - |
| Recall | - |
| Fields filled | - |
| Fields verified (of filled) | - |

*Recall is `found / expected` when the frame declares a size; otherwise read the saturation curve (new entities per pass) for whether the frame is exhausted.*

## Per-attribute completeness

| Attribute | Required | Fill rate | Verified rate |
|---|---|---|---|
| (attribute) | - | - | - |

## Roster

(The entity list with its key attributes, regenerated from `entities.csv`. Mark thin entities missing a required field.)

| Entity | (attribute) | (attribute) |
|---|---|---|
| - | - | - |

---

## Limitations

**What coverage measures.** Recall is only as good as the frame definition and the `expected_count`: a vague frame makes "complete" unfalsifiable. Where the size is unknown, coverage rests on the saturation curve, which can flatten because the frame is exhausted *or* because the search angle dried up.

**Field precision.** The verified rate reflects the mechanical citation check (the quote is on the cited page), not that the value is the *current* truth; a source can be right and stale. Flag attributes prone to change.

**Unattacked completeness.** A roster that has not drawn an active missing-entity pass is provisional; note which slices are still unattacked.

*Verbatim quotes, per-field detail, and all URLs: `data/`.*

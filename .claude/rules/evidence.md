---
description: Standardized source-to-certainty scoring and durable checkpointing for research agents
paths:
  - "scripts/**"
  - ".claude/skills/deep-research/**"
---

# Evidence scoring

How research agents turn sources into numerically grounded certainty, and how they
persist findings so a stalled agent does not lose its work. The reference
implementation is `scripts/vault_scripts/evidence.py` (`vault-tool evidence`); the
models are `EvidenceItem` / `ClaimVerdict` / `CitationRecord` / `Rubric` /
`ResearchManifest` in `_types.py`. Run `vault-tool evidence rubric` to print the
live convention.

## The evidence item

Every finding is one `EvidenceItem`, a single source bearing on a single claim.
One JSON object per line in an append-only shard:

```json
{"claim_id": "x-neuro-fluent", "claim": "X is fluent in neuroscience",
 "source_url": "https://pubmed.gov/26119352", "source_tier": "primary",
 "bearing": "supports", "strength": "strong", "quote": "Lodhi S, ...",
 "agent_id": "finder-3", "note": "", "v": 2}
```

Required: `claim_id`, `source_url`, `source_tier`, `bearing`. A `claim_id` is a
stable slug shared by every agent writing about that claim, so their evidence
composes. Always include a verbatim `quote` or datum; a claim with no quotable
source is not admissible evidence, and quotes are mechanically checked against
their URLs (see citation verification below), so a paraphrase gets the item
excluded. `v` stamps the schema version on every written line; a future breaking
change can then refuse stale shards deliberately instead of misreading them.

- `source_tier`: `primary` (own authorship, peer-reviewed work, official/license
  record), `community` (a named human recommendation), `secondary` (self-authored
  profile or practice-site copy), `weak` (aggregator rating, third-party listicle,
  inference).
- `strength`: `weak` | `moderate` | `strong`, how strongly this source bears on the
  claim.
- `bearing`: `supports` | `refutes`. The verifier moves certainty down by appending
  `refutes` items through the same rubric.

## The scoring model (weight of evidence, log-odds)

Each source contributes a signed weight of evidence in decibans (10 times the
log base 10 of the likelihood ratio). Certainty accumulates in log-odds, which is
additive and order-independent, so independent agents' shards compose by
summation and the result does not depend on who found what first.

- Base weight for a `strong` item, by tier: primary 12, community 8, secondary 6,
  weak 2 (decibans).
- Strength multiplier: weak 1/3, moderate 2/3, strong 1.
- `woe = sign(bearing) * tier_base * strength_mult`.
- `certainty = logistic(logit(prior) + sum(woe)/10 * ln10)`, mapped to 0 to 100.
- Prior defaults to 0.5 (neutral: no evidence leaves a claim at 50, "tentative").
- Independence guard: exact duplicates (same source, bearing, quote) count once, so
  a re-appended shard on resume does not double-count; and repeated items from the
  same host get diminishing weight (1.0, 0.5, 0.25) so one site cannot stack
  certainty.

**Ceiling gate.** Without at least one `supports` source of the ceiling tier
(`primary` by default), certainty is capped at 74, so a claim can reach "likely"
but not "confident" or "established" on weak sourcing alone.

**Confidence bands** (the report-facing labels): established (>=90), confident
(75 to 90), likely (55 to 75), tentative (35 to 55), speculative (15 to 35),
refuted (<15).

This is a consistency convention that makes results comparable across agents and
runs, not an empirically calibrated probability (calibration would need labeled
validation data). Treat the number as a standardized weight of evidence.

## Mechanical citation verification

Asking a verifier agent to check quotes is not the same as the quotes being
checked. `verify-citations` fetches every unique `(source_url, quote)` pair
(through an on-disk HTTP cache, so reruns are cheap) and records one
`CitationRecord` per pair in `<run-dir>/citations.jsonl`:

- `verified` — quote found on the live page, or on a Wayback snapshot when the
  page died or changed (`archived: true` marks the snapshot case: link rot, not
  fabrication).
- `quote_missing` — page (and snapshot, when one exists) fetched fine but the
  quote is not there: the strongest mechanical fabrication signal.
- `dead` — URL unreachable and no usable snapshot.
- `unfetchable` — cannot judge: bot-blocked, timeout, or non-text content.
- `no_quote` — the item carried no quote; nothing to check.

Matching is tag-stripped, case- and punctuation-insensitive, and shingle-tolerant
(word 5-grams, 60% threshold), so honest small edits survive and reconstructed
quotes do not.

`score` and `rank` fold the records in automatically when
`<run-dir>/citations.jsonl` exists (or pass `--citations <file>`): `verified`
items score as written, `quote_missing` items are excluded in either bearing,
and everything else is downgraded one strength level, so unverified sourcing can
still contribute but cannot carry a verdict.

## Ranking mode (rubric rollup)

A ranking question scores candidates against a weighted rubric. Each grid cell
is an ordinary claim with id `<candidate>--<criterion>`, scored by the same
engine as any other claim; the rubric only defines the rollup:

```json
{"criteria": [{"id": "fits-need", "text": "...", "weight": 2.0, "tier": "must"}],
 "candidates": [{"id": "option-a", "name": "Option A"}],
 "blocker_threshold": 50.0}
```

- fit score = weight-normalized mean of criterion certainties (0 to 100).
- `tier`: `blocker` (a cell below `blocker_threshold` marks the candidate blocked
  and caps its fit at that cell's certainty; blocked candidates always rank below
  clean ones), `must` (load-bearing), `should`, `nice`.
- A cell with no evidence sits at the prior (50): unknown, not failing. Thin
  load-bearing cells (under 2 sources) surface as `evidence_gaps`;
  `least_resolved` names the load-bearing criterion closest to 50, the natural
  target for a re-research round.

## Checkpointed run layout

A research run gets a directory under tmp (outside iCloud, so the vault's
iCloud write-race does not apply). Each agent owns one append-only shard and
appends every finding the moment it is produced, not just at the end:

```
<run-dir>/
  manifest.json       # ResearchManifest: question, facets, claim registry, rubric
  finder-1.jsonl      # one agent, one shard, append-only
  finder-2.jsonl
  verify-1.jsonl      # refuting/confirming items on the same claim_ids
  refine-1.jsonl      # targeted re-research on low-confidence claims
  citations.jsonl     # CitationRecords from verify-citations (not evidence)
  .http-cache/        # fetched pages, keyed by URL hash
```

A wall or disconnect costs only the in-flight line. On resume, completed shards
are reused as-is; `merge` is idempotent, so recombining is safe. A mangled line
is skipped but counted: every command reports `dropped_lines`, and a nonzero
count means an agent believes it recorded something that will never score.

The manifest registers the claim ids agents must share. `check` reconciles
shards against it: coined ids outside the registry are reported (allowed),
registered ids with no evidence are reported (coverage), and three things are
problems that exit nonzero: invalid lines, ids that look like rubric cells but
match none, and coined ids nearly identical to a registered id (a typo
fragmenting that claim's evidence).

## Commands

- `vault-tool evidence append --shard <path> --json '<EvidenceItem>'` — validate
  one item and durably append it (the write-as-you-go primitive). Append through
  the CLI, not by writing the line directly: a malformed direct write only
  surfaces as a dropped line at score time.
- `vault-tool evidence manifest --run-dir <dir> --json '<ResearchManifest>'` —
  validate and write the run manifest.
- `vault-tool evidence merge --run-dir <dir> [--out <file>]` — read, validate, and
  dedup all shards; idempotent.
- `vault-tool evidence verify-citations --run-dir <dir> [--cache-dir D] [--timeout N]`
  — mechanically check every cited pair; writes `citations.jsonl`.
- `vault-tool evidence check --run-dir <dir> [--manifest <file>]` — reconcile
  shards against the manifest; exits 3 when it finds problems.
- `vault-tool evidence score --run-dir <dir> [--markdown] [--prior P] [--ceiling C]
  [--ceiling-tier TIER] [--citations <file>]` — per-claim certainty, band, and the
  ranked driving sources with each one's decibans.
- `vault-tool evidence rank --run-dir <dir> [--rubric <file>] [--markdown] ...` —
  candidate fit scores and scorecard; the rubric defaults to the one in the run
  manifest.
- `vault-tool evidence rubric` — print the exact tier/strength/band mapping.

Shards and the run directory are disposable run artifacts (trackers tier rule):
the report note is the record; the shards live in tmp and die with the session.
Never copy shards or raw agent transcripts into the vault.

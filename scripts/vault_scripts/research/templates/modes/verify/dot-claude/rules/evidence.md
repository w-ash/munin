# Evidence Store Rules (verify)

The `data/` CSVs are the database: `claims.csv` (the claims under test) and append-only `evidence.csv` (source-graded rows attached to claims), plus any topic-specific extras. If docs disagree with the CSVs, the CSVs win. Certainty is never stored anywhere; the `research` CLI computes it from the evidence on every run (`vault-tool research score`), which is what keeps it honest.

## Scope (don't drift)

Unit of analysis: **a claim**. In scope: {{IN_SCOPE}}. Explicitly OUT: {{OUT_OF_SCOPE}}.

**The claim set is revisable, not open-ended.** A pass may split a claim that conflates two testable statements, or retire one that is out of scope; it does not invent new claims to chase. Record every change in the HANDOFF changelog. A claim is a single falsifiable statement, phrased so evidence can support or refute it.

## Certainty model (decibans)

Each source moves a claim's certainty by a fixed, tier-based log-likelihood increment, accumulated in log-odds so independent evidence composes order-independently. Certainty maps to bands; a ceiling gate holds the top bands without a supporting primary source. It is a consistency convention across sources, not automatically a calibrated probability; `vault-tool research calibrate` checks it against human labels in `data/gold.csv` when the topic has them.

- **Source tier** (base weight of evidence): `primary` (own authorship, peer-reviewed, official record), `community` (a named human recommendation), `secondary` (self-authored profile, practice-site copy), `weak` (aggregator rating, third-party listicle, inference).
- **Strength** scales the tier weight: `weak` (1/3), `moderate` (2/3), `strong` (1).
- **Bearing**: `supports` adds, `refutes` subtracts.
- **Same-domain diminishing returns**: the 2nd and 3rd source sharing a host count half then a quarter, so one site can't stack certainty by restating itself.
- **No-primary ceiling** (`research.toml` `[verify] ceiling`, default 74%): a claim with no *supporting* primary source is held below the top bands, so "confident"/"established" always rest on a primary source. A refuting primary does not lift the ceiling.
- **Bands**: established >= 90% | confident >= 75% | likely >= 55% | tentative >= 35% | speculative >= 15% | refuted below.

## Conventions

- **Append-only evidence**, with carve-outs: set `claim_id` to `VOID` to retire a row whose evidence fails audit; supersede a changed source with a newer-dated row.
- **Capture verbatim** into `quote`; don't translate the source's wording into our jargon.
- **Evidence-backed only**; no invented findings, no guessed URLs. Every row needs a real `source_url` and a `quote`.
- **Grade honestly:** `source_tier` and `strength` are the scorer's only inputs besides bearing. Inflating them is how a claim reads "confident" on thin sourcing; the citation pass and the no-primary ceiling are the guards.
- **Competing-cause preset (diagnosis):** a "why did X happen" investigation rides this mode. Frame the candidate causes as claims, gather evidence for and against each, and read the ranking of certainties; aim the active refutation at the leading cause.
- **`vault-tool research verify` before scoring:** it fetches every cited URL and checks the quote is actually on the page (Wayback fallback for dead links), writing verdicts to `data/citations.csv`. The scorer then **excludes** `quote_missing` rows and **downgrades** unverified ones one strength level before computing certainty. Resolve `quote_missing`/`dead` rows (fix the quote or `VOID` the row) before the gate.
- **`vault-tool research check` gates every pass:** zero errors before the baton rotates.

## Active refutation

The claims the report leans on earn their certainty by surviving attack. For each claim in a top band (`confident`/`established`), a fresh-context skeptic hunts refuting primary sources and newer information that supersedes the finding; confirmed contradictions log as normal `refutes` rows and subtract in the log-odds. Flag temporally stale sources (superseded by a later authority), not just missing quotes.

## Synthesis discipline

`SYNTHESIS.md` is a synthesis of the evidence, never a place for opinions. It carries only what the evidence supports: the per-claim verdict table and what the certainties add up to. Keep prescriptions ("act on X", "trust Y") and any claim not traceable to `data/` out; those belong in `narrative/`, framed as the reader's to weigh.

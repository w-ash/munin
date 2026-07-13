# Evidence Store Rules (estimate)

The `data/` CSVs are the database: `factors.csv` (the decomposition, one row per factor with its range) and append-only `evidence.csv` (sourced observations backing each factor), plus any topic-specific extras. If docs disagree with the CSVs, the CSVs win. The magnitude is never stored anywhere; the `research` CLI recomputes it from the factors on every run (`vault-tool research score`), which is what keeps it honest.

## Scope (don't drift)

Unit of analysis: **a factor**. The target being sized: {{TARGET_QUANTITY}}.

**Present-state only.** This mode sizes what *is* now. Forward-looking prediction is a separate (deferred) shape; do not let a factor smuggle in a growth forecast. The decomposition is revisable: a pass may split a factor that conflates two things or drop one that double-counts, logging the change in the HANDOFF changelog.

## Propagation model (lognormal factors, structure-chosen path)

Each factor is a lognormal read from a low/high 90% interval; the scorer combines them and reports a median with a confidence interval.

- **Factor range**: `low`/`high` bracket a 90% interval (the finder is ~90% sure the value falls inside), and `mid` is the median (blank = the geometric mean of low/high). `low`/`high` must be positive (lognormal).
- **Operator** (`op`): `mul`/`div` combine factors within a product term; `add`/`sub` start a new signed term. Factors read left-to-right the way arithmetic does, so `a*b + c*d` is two terms summed.
- **Path selection** (automatic, by structure):
  - **Pure product/quotient** (every `op` is `mul` or `div`): the product of independent lognormals is lognormal in closed form, propagated **analytically**. Exact and deterministic. This is the classic Fermi shape; prefer it.
  - **Sums or mixed** (any `add`/`sub`): a sum of lognormals has no closed form, so the scorer falls back to seeded **Monte Carlo** (`research.toml` `[estimate] mc_samples`/`mc_seed`). The fixed seed keeps the estimate reproducible.
- **Dominant uncertainty**: the factor with the largest share of the total log-variance. It is the swing driver and the natural target for the next re-sizing pass.
- Interval arithmetic (multiplying the lows, multiplying the highs) is deliberately not used: it assumes worst-case correlation and compounds into a uselessly wide band.

## Conventions

- **Independence and no double-counting**: the factors must be independent and must multiply/add to the target. Overlapping factors bias both the point and the interval; split or merge them so each counts once.
- **Append-only evidence**, with carve-outs: set `factor_id` to `VOID` to retire a row whose sourcing fails audit; supersede a changed source with a newer-dated row.
- **Capture verbatim** into `quote`, with the units and the date; a figure without units is not usable.
- **Range, not false precision**: a wide interval honestly sourced beats a narrow one you cannot defend. Do not collapse a genuinely uncertain factor to a point.
- **`vault-tool research verify` before scoring:** it fetches every cited URL and checks the quote is on the page (Wayback fallback), writing verdicts to `data/citations.csv`. Resolve `quote_missing`/`dead` rows (fix the quote or `VOID` the row) before the gate.
- **`vault-tool research check` gates every pass:** zero errors before the baton rotates.

## Active refutation

The estimate leans on its widest factor (the dominant uncertainty), so that factor earns its range by surviving attack. A fresh-context skeptic hunts for sources that widen or recenter it, and challenges the largest-magnitude factor; confirmed revisions are applied centrally and re-scored. Flag factors resting on stale figures, not just missing quotes.

## Synthesis discipline

`SYNTHESIS.md` is a synthesis of the estimate, never a place for opinions. It carries only what the evidence supports: the target median and interval, the propagation method, and the factor table. Keep prescriptions ("the market is worth pursuing") and any claim not traceable to `data/` out; those belong in `narrative/`, framed as the reader's to weigh.

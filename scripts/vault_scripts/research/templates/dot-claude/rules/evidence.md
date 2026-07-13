# Evidence Store Rules

The `data/` CSVs are the database: `taxonomy.csv` (categories), append-only `evidence.csv`, `sources.csv`, plus any topic-specific extras. If docs disagree with the CSVs, the CSVs win. Confidence is never stored anywhere; the `research` CLI computes it from the evidence on every run (`vault-tool research status`), which is what keeps it honest.

## Scope (don't drift)

Unit of analysis: **{{UNIT}}**. In scope: {{IN_SCOPE}}. Explicitly OUT: {{OUT_OF_SCOPE}}.

**Open taxonomy:** the category list is not fixed. Recurring material with a distinct purpose that fits no category cleanly gets a **new category** (next free id), never force-fit. Promotion bar: **2+ units, multiple findings each, and a purpose no existing category can absorb**; short of that it stays on the watch list ({{WATCH_LIST}}).

## Confidence model (v3, falsifiable)

`confidence = max(0%, min(cap, step x supporting units) - step x diverging units)`, with step and cap in `research.toml` (defaults 10% and 95%). Low until 5+ net units; tiers High >= 85% · Medium-High 65-84% · Medium 50-64% · Low < 50%. Supporting evidence caps at 95% (the last 5% needs primary validation); **divergence subtracts after the cap**, so counter-evidence never saturates and a fully capped category still loses one step per diverging unit.

**Primary-source ceiling:** a category with no primary source is held at `primary_ceiling` (default 84%, the top of Medium-High), so reaching **High** always rests on at least one primary source. A supporting row whose `source_type` is primary (see `primary_source_types` in `research.toml`) clears the bar; so does a validated entry in the optional `data/individuals.csv`. `vault-tool research status` shows a `prim` column for which categories cleared it.

**Divergence vs near-miss vs null** (the distinctions matter; they're handled differently):

- **Divergence** (`<id>-div` category id): a unit occupies the category's space with a materially *different purpose or accountability* than the category defines; the material exists but contradicts the synthesized definition or boundary. Logged as a normal evidence row (verbatim capture of *what* differs); the critic must confirm it before logging; it subtracts from confidence. Divergences arrive two ways: a finder flags one in passing, or a **High-tier category draws an active refutation pass** (a fresh-context skeptic hunts disconfirming and superseding evidence), so the report's load-bearing claims are the ones attacked hardest. Either way the critic confirms before it logs.
- **Near-miss**: material that doesn't fit and doesn't contradict. Goes to `taxonomy.csv` `notes_coverage`, never to evidence.
- **Null**: unit searched, no qualifying material found. Structured note in `notes_coverage` (`Null (Pass N): <unit> - <interpretation>`); nulls stay out of the math. Absence in public sources is weak evidence (sampling misses stable material); divergence is strong evidence and gets the formula.

**Taxonomy audits (every 3rd pass)** review the full evidence log against the boundaries and the accumulated `-div` rows: **2+ units diverging the same way means amend the category definition or split a new category** (update `taxonomy.csv` and the changelog), then re-judge the old `-div` rows in place, since they may now support. `vault-tool research check` surfaces audit candidates mechanically: it warns when a category is **contested** (diverging units >= supporting units) or has **only divergent evidence**, and when two unit strings are **near-duplicates** (e.g. `Acme Inc` vs `Acme Inc.`) that would split a unit's corroboration. Empty categories are never warned; empty is normal for many passes.

## Conventions

- **Append-only evidence**, with three carve-outs: tag corrections happen **in place** (a superseding row would double-count the unit); set `category_id` to `VOID` to retire a row whose evidence fails audit; supersede with a newer-dated row for content changes.
- `<id>-ref` marks a deliberate reference row excluded from all counts (for example a scope anchor kept for context).
- **Capture verbatim**; don't translate the source's wording into our jargon.
- **Evidence-backed only**; no invented findings, no guessed URLs.
- **Curate before logging:** check each finding against the category's *purpose*, never just its surface keywords; near-misses go to taxonomy notes.
- **Canonical unit names:** distinct-unit counting compares exact strings. `research.toml` `units` is the canonical list and `vault-tool research check` enforces it; subsidiary or component evidence logs under the parent unit.
- **Published dates** in `published_date` when shown; flag stale sources (12+ months) in `detail_quote`.
- **`vault-tool research check` gates every pass:** zero errors before the baton rotates.

## Synthesis discipline

`SYNTHESIS.md` is a synthesis of the evidence, never a place for opinions. It carries only what the evidence supports. Keep these out:

- **Build/design/sell prescriptions** ("design for X", "position for Y", "build Z"). What the findings imply for action belongs in `narrative/`, framed there as possible approaches for the reader to weigh.
- **Any claim not traceable to the `data/` CSVs.** If it isn't in the store, it isn't synthesis; it's a presumption. Surface it in `narrative/` as an open question instead of stating it as fact.

When a re-sync is tempted to add a "so what, go do it" line, that is the signal it belongs in `narrative/`.

# Evidence Store Rules (find)

The `data/` CSVs are the database: `entities.csv` (the roster, one row per entity with an attribute column per field), `attributes.csv` (the fields to extract), and append-only `evidence.csv` (one sourced observation per cell), plus any topic-specific extras. If docs disagree with the CSVs, the CSVs win. Coverage is never stored anywhere; the `research` CLI computes it from the roster and evidence on every run (`vault-tool research score`), which is what keeps it honest.

## Scope (don't drift)

Unit of analysis: **an entity**. The frame is the boundary: {{FRAME_DEFINITION}}.

**The frame is revisable, not open-ended.** A pass may tighten or widen it, but every entity is judged against the *current* frame, and every change is logged in the HANDOFF changelog. Enumerating against a named, bounded population is what makes "complete" measurable; drift into a vague frame makes recall meaningless.

## Coverage model (recall + per-field verification)

The quality bar is not a certainty number; it is **completeness** and **precision**.

- **Recall**: `found / expected_count` when the frame is a known-size set (`research.toml` `[find] expected_count`); otherwise the per-pass **saturation** curve (new entities each pass), which flattens as the frame is exhausted. Only `in_frame` entities count toward recall.
- **Field fill**: the fraction of (in-frame entity x attribute) cells that carry a value. A blank cell is an honest gap; a guessed value is not.
- **Field verified**: of the filled cells, the fraction whose source passed the mechanical citation check (`vault-tool research verify`). This is the precision signal.
- **Thin entities**: in-frame entities missing a `required` attribute, the natural backfill target.

## Conventions

- **Append-only evidence**, with carve-outs: set an entity's `in_frame` to a false value (or a cell's `cell_id` to `VOID`) to retire a wrong membership or field; supersede a changed source with a newer-dated row.
- **Cell keying**: every evidence row's `cell_id` is `<entity_id>--<attribute_id>`, tying one sourced observation to one field of one entity.
- **Capture verbatim** into `quote`; don't translate the source's wording into our jargon.
- **Evidence-backed only**; no invented entities, no guessed URLs, no fabricated field values. Every filled cell needs a real `source_url` and a `quote`, and a profile URL must resolve to the right entity.
- **Membership honesty:** an entity is `in_frame` only when it clearly matches the frame; a near-miss is logged with `in_frame` false and a reason rather than dropped, so the judgment is on record.
- **`vault-tool research verify` before scoring:** it fetches every cited URL and checks the quote is actually on the page (Wayback fallback for dead links), writing verdicts to `data/citations.csv`. The scorer reads those as the per-field verified signal. Resolve `quote_missing`/`dead` rows (fix the quote or `VOID` the cell) before the gate.
- **`vault-tool research check` gates every pass:** zero errors before the baton rotates.

## Active refutation

The roster leans on being *complete*, so completeness earns its standing by surviving attack. A fresh-context skeptic hunts for entities in the frame the roster is missing, and challenges any `in_frame` membership that looks like a false positive; confirmed additions and removals are applied centrally. Report coverage gaps rather than letting them pass silently.

## Synthesis discipline

`SYNTHESIS.md` is a synthesis of the roster, never a place for opinions. It carries only what the evidence supports: the coverage metrics, the per-attribute completeness, and the roster itself. Keep prescriptions ("go contact X", "prioritize Y") and any claim not traceable to `data/` out; those belong in `narrative/`, framed as the reader's to weigh.

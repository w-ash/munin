"""Per-mode Sheet mirror content: computed blocks and doc tabs.

``MODE_MIRRORS`` is the mirror half of the mode registry (schema:
``store.MODE_SCHEMAS``; scoring: ``score.MODE_SCORERS``). Each entry builds
the ``sheets.SheetExtras`` for one mode — which store tab carries which
computed columns, joined on the mode's id column, plus the doc tab that
explains how to read the numbers with the topic's actual parameters.

Lives apart from ``score`` because ``sheets`` pulls in the Google auth and REST
transport; ``cmd_sync`` lazy-imports this module alongside ``sheets`` so a plain
``research score`` never loads that stack.
"""

from collections.abc import Callable

from vault_scripts.research import score, sheets, store

# Every doc tab ends the same way; the mirror contract does not vary by mode.
_CLOSER = (
    "",
    "This Sheet is a one-way mirror computed by the `research` CLI from "
    "the topic's data/ CSVs. Treat it as read-only: the next push "
    "overwrites manual edits.",
)


def _map_extras(topic: store.Topic) -> sheets.SheetExtras:
    """Taxonomy tab gains the per-category confidence block."""
    rows = {
        r.category_id: (
            r.supporting_units,
            r.diverging_units,
            r.evidence_count,
            r.confidence,
            r.tier,
            "yes" if r.primary_backed else "no",
        )
        for r in score.map_rows(topic)
    }
    block = sheets.ComputedBlock(
        csv_name=store.TAXONOMY_CSV,
        join_column="category_id",
        columns=(
            "supporting_units",
            "diverging_units",
            "evidence_count",
            "confidence",
            "tier",
            "primary_backed",
        ),
        rows=rows,
        percent_columns=frozenset({"confidence"}),
    )
    params = topic.config.params
    step = f"{params.step:.0%}"
    cap = f"{params.cap:.0%}"
    noun = topic.config.unit_noun
    lines = (
        f"Confidence model for: {topic.config.title}",
        "",
        f"confidence = max(0%, min({cap}, {step} x supporting {noun}s) "
        f"- {step} x diverging {noun}s)",
        "",
        f"Breadth-based and falsifiable: corroboration across distinct {noun}s "
        "raises confidence; divergence lowers it.",
        f"Divergence subtracts after the {cap} cap, so counter-evidence never "
        "saturates: a fully capped category still loses "
        f"{step} per diverging {noun}.",
        f"Supporting evidence caps at {cap}; the last slice needs primary validation.",
        f"A category with no primary source is held at {params.primary_ceiling:.0%} "
        "(the primary_backed column shows which cleared the bar), so 'High' "
        "always rests on a primary source.",
        "Tiers: High >= 85% | Medium-High 65-84% | Medium 50-64% | Low < 50%. "
        f"Low until 5+ net {noun}s.",
        "",
        "Divergence rows carry a '-div' suffix on their category id; '-ref' "
        "rows and VOID rows are excluded from all counts.",
        *_CLOSER,
    )
    return sheets.SheetExtras(
        blocks=(block,), doc_title="Confidence model", doc_lines=lines
    )


def _verify_extras(topic: store.Topic) -> sheets.SheetExtras:
    """Claims tab gains the per-claim certainty block."""
    rows = {
        v.claim_id: (
            v.certainty,
            v.band,
            v.net_decibans,
            v.n_sources,
            "yes" if v.capped else "no",
        )
        for v in score.verify_rows(topic)
    }
    block = sheets.ComputedBlock(
        csv_name=store.CLAIMS_CSV,
        join_column="claim_id",
        columns=("certainty", "band", "net_decibans", "n_sources", "capped"),
        rows=rows,
        # certainty is 0-100, not 0-1: no percent formatting.
    )
    params = topic.config.certainty_params
    lines = (
        f"Certainty model for: {topic.config.title}",
        "",
        "Each source moves a claim's certainty by a tier-based log-likelihood "
        "increment (decibans), accumulated in log-odds so evidence composes "
        "order-independently.",
        "Tier weights (strong item): primary 12 dB | community 8 dB | "
        "secondary 6 dB | weak 2 dB; strength scales by 1/3 (weak), "
        "2/3 (moderate), 1 (strong); bearing signs it (supports adds, "
        "refutes subtracts).",
        "Sources sharing a host diminish (1.0 / 0.5 / 0.25) so one site "
        "cannot stack certainty by restating itself.",
        f"A claim with no supporting {params.ceiling_tier} source is capped at "
        f"{params.ceiling:g}% (the capped column shows which hit it).",
        "Certainty is 0-100. Bands: established >= 90 | confident >= 75 | "
        "likely >= 55 | tentative >= 35 | speculative >= 15 | refuted below.",
        "",
        "It is a consistency convention across sources, not automatically a "
        "calibrated probability; `research calibrate` checks it against "
        "human labels in data/gold.csv when the topic has them.",
        *_CLOSER,
    )
    return sheets.SheetExtras(
        blocks=(block,), doc_title="Certainty model", doc_lines=lines
    )


def _rank_extras(topic: store.Topic) -> sheets.SheetExtras:
    """Candidates tab gains the fit rollup block."""
    rows = {
        v.candidate_id: (
            v.score,
            "yes" if v.blocked else "no",
            ", ".join(v.blocked_by),
            v.least_resolved or "",
            ", ".join(v.evidence_gaps),
        )
        for v in score.rank_rows(topic)
    }
    block = sheets.ComputedBlock(
        csv_name=store.CANDIDATES_CSV,
        join_column="candidate_id",
        columns=("score", "blocked", "blocked_by", "least_resolved", "evidence_gaps"),
        rows=rows,
        # score is 0-100, not 0-1: no percent formatting.
    )
    lines = (
        f"Fit model for: {topic.config.title}",
        "",
        "Each candidate x criterion cell is a claim scored by the verify "
        "certainty engine (decibans: tier x strength, signed by bearing, "
        "same-domain diminishing returns, no-primary ceiling); an empty cell "
        "sits at the 50% prior.",
        "Fit (the score column, 0-100) is the weight-normalized mean over the "
        "criteria; a blocker criterion below the threshold caps the fit and "
        "sorts the candidate below every clean one (the blocked/blocked_by "
        "columns).",
        "least_resolved names the thinnest load-bearing criterion; "
        "evidence_gaps lists load-bearing cells resting on fewer than two "
        "sources. Per-cell certainty lives in the `research score` envelope, "
        "not on this Sheet.",
        "",
        "Fit is a consistency convention over graded sources, not "
        "automatically a calibrated score; `research calibrate` checks "
        "per-cell certainty against human labels in data/gold.csv.",
        *_CLOSER,
    )
    return sheets.SheetExtras(blocks=(block,), doc_title="Fit model", doc_lines=lines)


def _find_extras(topic: store.Topic) -> sheets.SheetExtras:
    """Attributes tab gains the per-field coverage block; the frame-level
    recall story lives on the doc tab (the scorer's unit is the attribute,
    not the entity, so the roster tab stays a pure passthrough)."""
    report = score.find_report(topic)
    rows = {
        a.attribute_id: (a.n_filled, a.n_verified, a.fill_rate, a.verified_rate)
        for a in report.per_attribute
    }
    block = sheets.ComputedBlock(
        csv_name=store.ATTRIBUTES_CSV,
        join_column="attribute_id",
        columns=("n_filled", "n_verified", "fill_rate", "verified_rate"),
        rows=rows,
        percent_columns=frozenset({"fill_rate", "verified_rate"}),
    )
    recall = f"{report.recall:.1%}" if report.recall is not None else "n/a"
    frame_line = f"Found {report.found} in-frame entities" + (
        f" of {report.expected} expected (recall {recall})."
        if report.expected
        else " (no declared frame size; read the saturation curve)."
    )
    saturation = (
        "Saturation (new in-frame entities per pass): "
        + "; ".join(f"pass {p}: {n}" for p, n in report.saturating)
        if report.saturating
        else "Saturation: no passes recorded yet."
    )
    thin = (
        "Thin entities (missing a required field): " + ", ".join(report.thin_entities)
        if report.thin_entities
        else "No thin entities: every in-frame entity has its required fields."
    )
    lines = (
        f"Coverage model for: {topic.config.title}",
        "",
        f"Frame: {topic.config.find_frame}",
        frame_line,
        f"Fields: {report.field_fill:.0%} filled; {report.field_verified:.0%} "
        "of filled fields verified (a field counts verified when `research "
        "verify` confirms its source quote).",
        saturation,
        thin,
        "",
        "The quality bar is completeness and precision over the named frame, "
        "not a certainty number: recall says whether everyone was found, the "
        "per-field rates say whether the fields are right.",
        *_CLOSER,
    )
    return sheets.SheetExtras(
        blocks=(block,), doc_title="Coverage model", doc_lines=lines
    )


def _estimate_extras(topic: store.Topic) -> sheets.SheetExtras:
    """Factors tab gains the log-space parameter block; the propagated
    magnitude lives on the doc tab (one number per topic, not per row)."""
    result = score.estimate_result(topic)
    rows = {s.factor_id: (s.mu, s.sigma, s.variance_share) for s in result.factors}
    block = sheets.ComputedBlock(
        csv_name=store.FACTORS_CSV,
        join_column="factor_id",
        columns=("mu", "sigma", "variance_share"),
        rows=rows,
        percent_columns=frozenset({"variance_share"}),
    )
    lines = (
        f"Estimate model for: {topic.config.title}",
        "",
        f"Estimate ({result.method}): {result.median:g}  "
        f"[{result.ci:.0f}% CI {result.low:g} .. {result.high:g}]",
        f"Dominant uncertainty: {result.dominant_factor or '-'} (largest "
        "variance_share; the natural refutation target).",
        "",
        "Each factor is a lognormal read from its low/high 90% interval; mu "
        "and sigma are its log-space median and spread. A pure product/"
        "quotient propagates in closed form (analytic-lognormal); any "
        "additive term falls back to seeded Monte Carlo.",
        "variance_share is the factor's share of the total log-variance: "
        "tightening the largest shares narrows the interval fastest.",
        *_CLOSER,
    )
    return sheets.SheetExtras(
        blocks=(block,), doc_title="Estimate model", doc_lines=lines
    )


# Keyed by the same names as store.MODE_SCHEMAS; a parity test ties the two.
MODE_MIRRORS: dict[str, Callable[[store.Topic], sheets.SheetExtras]] = {
    "map": _map_extras,
    "verify": _verify_extras,
    "rank": _rank_extras,
    "find": _find_extras,
    "estimate": _estimate_extras,
}

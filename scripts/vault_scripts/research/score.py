# pyright: reportAny=false, reportExplicitAny=false
# Vendored research harness: this module reads the CSV store, boundaries where the
# stdlib hands back `Any`. reportAny/reportExplicitAny are above
# basedpyright's standard strict (which this file passes); every other
# strict check still applies.
"""Mode-dispatched scoring: one ``research score`` command, one scorer per mode.

``MODE_SCORERS`` is the scoring half of the mode registry (the schema half is
``store.MODE_SCHEMAS``). Each entry is a ``Scorer``: it assembles inputs from
the loaded ``Topic``, runs the mode's pure scoring engine, and renders a
``ScoreReport`` — stderr table lines plus the JSON envelope payload — so a new
mode adds a registry row here without touching the CLI. Scores are computed,
never stored.

The per-mode row-builders (``map_rows``, ``verify_rows``, ...) are the shared
assembly seam: scorers render them, ``MODE_CALIBRATORS`` checks them against
the human labels in ``data/gold.csv``, and the Sheet mirror consumes them.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from vault_scripts.research import (
    calibration,
    certainty,
    coverage,
    magnitude,
    store,
    verify,
)
from vault_scripts.research.confidence import CELL_SEP, CategoryConfidence, compute_all


@dataclass(frozen=True)
class ScoreReport:
    """One scoring run, rendered: human-readable lines + envelope fields.

    ``table`` goes to stderr line by line; ``envelope`` becomes the JSON
    result (the CLI appends ``counts``). Deliberately untyped beyond that so
    the registry value type stays mode-agnostic.
    """

    table: list[str]
    envelope: dict[str, Any]


Scorer = Callable[[store.Topic], ScoreReport]


def map_rows(topic: store.Topic) -> list[CategoryConfidence]:
    """The map scorer's typed rows; the Sheet mirror consumes these directly."""
    return compute_all(
        topic.taxonomy_ids,
        topic.evidence_pairs(),
        topic.config.params,
        store.primary_backed_categories(topic),
    )


def score_map(topic: store.Topic) -> ScoreReport:
    """`map`: v3 falsifiable breadth confidence per taxonomy category."""
    results = map_rows(topic)
    names = {r["category_id"]: r["name"] for r in topic.tables[store.TAXONOMY_CSV].rows}

    header = (
        f"{'id':<8} {'name':<32} {'sup':>4} {'div':>4} {'rows':>5} "
        f"{'conf':>6} {'prim':>4} tier"
    )
    table = [header, "-" * len(header)]
    for r in results:
        primary = "yes" if r.primary_backed else "no"
        table.append(
            f"{r.category_id:<8} {names.get(r.category_id, ''):<32.32} "
            f"{r.supporting_units:>4} {r.diverging_units:>4} {r.evidence_count:>5} "
            f"{r.confidence:>6.0%} {primary:>4} {r.tier}"
        )

    envelope: dict[str, Any] = {
        "topic": topic.config.title,
        "categories": [
            {
                "category_id": r.category_id,
                "name": names.get(r.category_id, ""),
                "supporting_units": r.supporting_units,
                "diverging_units": r.diverging_units,
                "evidence_count": r.evidence_count,
                "confidence": r.confidence,
                "primary_backed": r.primary_backed,
                "tier": r.tier,
            }
            for r in results
        ],
    }
    return ScoreReport(table=table, envelope=envelope)


def verify_rows(topic: store.Topic) -> list[certainty.ClaimVerdict]:
    """The verify scorer's typed per-claim verdicts, citations folded in."""
    items = topic.verify_evidence()
    verdicts_by_id = verify.read_citations(topic)
    if verdicts_by_id:
        items, _stats = certainty.apply_citations(items, verdicts_by_id)
    claim_ids = [r["claim_id"] for r in topic.tables[store.CLAIMS_CSV].rows]
    return certainty.score_items(items, claim_ids, params=topic.config.certainty_params)


def score_verify(topic: store.Topic) -> ScoreReport:
    """`verify`: source-weighted certainty (decibans) per claim."""
    results = verify_rows(topic)
    names = {r["claim_id"]: r["claim"] for r in topic.tables[store.CLAIMS_CSV].rows}

    header = f"{'claim':<10} {'text':<40} {'cert':>6} {'band':>12} {'src':>4} {'net dB':>7} cap"
    table = [header, "-" * len(header)]
    for v in results:
        cap = "yes" if v.capped else ""
        table.append(
            f"{v.claim_id:<10} {names.get(v.claim_id, ''):<40.40} "
            f"{v.certainty:>5.1f}% {v.band:>12} {v.n_sources:>4} "
            f"{v.net_decibans:>+7.2f} {cap}"
        )

    envelope: dict[str, Any] = {
        "topic": topic.config.title,
        "claims": [
            {
                "claim_id": v.claim_id,
                "claim": names.get(v.claim_id, ""),
                "certainty": v.certainty,
                "band": v.band,
                "net_decibans": v.net_decibans,
                "n_sources": v.n_sources,
                "capped": v.capped,
            }
            for v in results
        ],
    }
    return ScoreReport(table=table, envelope=envelope)


def rank_rows(topic: store.Topic) -> list[certainty.CandidateVerdict]:
    """The rank scorer's typed per-candidate verdicts, citations folded in."""
    items = topic.rank_evidence()
    verdicts_by_id = verify.read_citations(topic)
    if verdicts_by_id:
        items, _stats = certainty.apply_citations(items, verdicts_by_id)
    return certainty.rank_candidates(
        items,
        topic.rank_candidates(),
        topic.rank_criteria(),
        params=topic.config.certainty_params,
        blocker_threshold=topic.config.rank_blocker_threshold,
    )


def score_rank(topic: store.Topic) -> ScoreReport:
    """`rank`: candidate x criterion rubric fit, with blocker gating."""
    results = rank_rows(topic)

    header = f"{'rank':>4}  {'candidate':<24} {'fit':>6}  {'status':<20} least-resolved"
    table = [header, "-" * len(header)]
    for i, v in enumerate(results, start=1):
        status = ("blocked: " + ", ".join(v.blocked_by)) if v.blocked else "ok"
        table.append(
            f"{i:>4}  {v.candidate:<24.24} {v.score:>5.1f}%  {status:<20.20} "
            f"{v.least_resolved or '-'}"
        )

    envelope: dict[str, Any] = {
        "topic": topic.config.title,
        "candidates": [
            {
                "candidate_id": v.candidate_id,
                "candidate": v.candidate,
                "score": v.score,
                "blocked": v.blocked,
                "blocked_by": v.blocked_by,
                "least_resolved": v.least_resolved,
                "evidence_gaps": v.evidence_gaps,
                "criteria": [
                    {
                        "criterion_id": s.criterion_id,
                        "tier": s.tier,
                        "certainty": s.certainty,
                        "band": s.band,
                        "n_sources": s.n_sources,
                        "capped": s.capped,
                    }
                    for s in v.criteria
                ],
            }
            for v in results
        ],
    }
    return ScoreReport(table=table, envelope=envelope)


def find_report(topic: store.Topic) -> coverage.CoverageReport:
    """The find scorer's typed coverage report, citation verdicts folded in."""
    entities = topic.find_entities()
    attributes = topic.find_attributes()
    observations = topic.find_observations()
    citations = verify.read_citations(topic)
    verified_ids = frozenset(
        eid for eid, status in citations.items() if status == verify.VERIFIED
    )
    cells = coverage.field_cells(entities, attributes, observations, verified_ids)
    return coverage.coverage(
        entities, attributes, cells, expected_count=topic.config.find_expected_count
    )


def score_find(topic: store.Topic) -> ScoreReport:
    """`find`: recall over the named frame plus per-field verification."""
    report = find_report(topic)

    recall = f"{report.recall:.1%}" if report.recall is not None else "n/a"
    frame_line = f"frame: found {report.found}" + (
        f" / {report.expected} expected (recall {recall})"
        if report.expected
        else " (no declared size; read the saturation curve)"
    )
    header = f"{'attribute':<20} {'req':>3} {'fill':>6} {'verified':>9}"
    table = [
        frame_line,
        f"fields: {report.field_fill:.0%} filled, "
        f"{report.field_verified:.0%} of filled verified",
        header,
        "-" * len(header),
    ]
    for a in report.per_attribute:
        req = "yes" if a.required else ""
        table.append(
            f"{a.name:<20.20} {req:>3} {a.fill_rate:>6.0%} {a.verified_rate:>9.0%}"
        )
    if report.thin_entities:
        table.append(f"thin (missing required): {', '.join(report.thin_entities)}")

    envelope: dict[str, Any] = {
        "topic": topic.config.title,
        "frame": topic.config.find_frame,
        "expected": report.expected,
        "found": report.found,
        "recall": report.recall,
        "field_fill": report.field_fill,
        "field_verified": report.field_verified,
        "saturating": [{"pass": p, "new": n} for p, n in report.saturating],
        "attributes": [
            {
                "attribute_id": a.attribute_id,
                "name": a.name,
                "required": a.required,
                "n_filled": a.n_filled,
                "n_verified": a.n_verified,
                "fill_rate": a.fill_rate,
                "verified_rate": a.verified_rate,
            }
            for a in report.per_attribute
        ],
        "thin_entities": report.thin_entities,
    }
    return ScoreReport(table=table, envelope=envelope)


def estimate_result(
    topic: store.Topic, factors: list[magnitude.Factor] | None = None
) -> magnitude.EstimateResult:
    """The estimate scorer's typed result, propagated per the topic's config.
    Pass ``factors`` to reuse an already-parsed list instead of re-reading the CSV.
    """
    return magnitude.estimate(
        topic.estimate_factors() if factors is None else factors,
        ci=topic.config.estimate_ci,
        mc_samples=topic.config.estimate_mc_samples,
        mc_seed=topic.config.estimate_mc_seed,
    )


def score_estimate(topic: store.Topic) -> ScoreReport:
    """`estimate`: a target magnitude with a propagated uncertainty interval."""
    factors = topic.estimate_factors()
    result = estimate_result(topic, factors)
    mids = {
        f.factor_id: (f.mid if f.mid > 0 else (f.low * f.high) ** 0.5) for f in factors
    }

    header = f"{'factor':<18} {'op':>4} {'median':>13} {'sigma':>7} {'var share':>10}"
    table = [
        f"estimate ({result.method}): {result.median:g}  "
        f"[{result.ci:.0f}% CI {result.low:g} .. {result.high:g}]",
        f"dominant uncertainty: {result.dominant_factor or '-'}",
        header,
        "-" * len(header),
    ]
    table.extend(
        f"{s.name:<18.18} {s.op:>4} {mids[s.factor_id]:>13.4g} "
        f"{s.sigma:>7.3f} {s.variance_share:>10.1%}"
        for s in result.factors
    )

    envelope: dict[str, Any] = {
        "topic": topic.config.title,
        "method": result.method,
        "median": result.median,
        "low": result.low,
        "high": result.high,
        "ci": result.ci,
        "dominant_factor": result.dominant_factor,
        "factors": [
            {
                "factor_id": s.factor_id,
                "name": s.name,
                "op": s.op,
                "mu": s.mu,
                "sigma": s.sigma,
                "variance_share": s.variance_share,
            }
            for s in result.factors
        ],
    }
    return ScoreReport(table=table, envelope=envelope)


# Keyed by the same names as store.MODE_SCHEMAS; a parity test ties the two.
MODE_SCORERS: dict[str, Scorer] = {
    "map": score_map,
    "verify": score_verify,
    "rank": score_rank,
    "find": score_find,
    "estimate": score_estimate,
}


def _read_gold[T](
    topic: store.Topic, value_column: str, parse_cell: Callable[[str, int], T]
) -> dict[str, T]:
    """Parse ``data/gold.csv`` into item_id -> value via ``parse_cell``.

    Shared by the reliability readers (label) and estimate (actual). id
    integrity (a non-empty, unique ``item_id``) is not re-checked here: the
    store's generic ``_check_ids`` already guards it for gold.csv like every
    other ``*_id`` table, and ``research calibrate`` runs behind that check.
    ``parse_cell`` gets the raw, unstripped cell and owns its value
    validation. Items the author hasn't judged are simply omitted.
    """
    table = topic.tables[store.GOLD_CSV]
    missing = [c for c in ("item_id", value_column) if c not in table.columns]
    if missing:
        raise ValueError(
            f"{store.GOLD_CSV}: missing required column(s): {', '.join(missing)}"
        )
    return {
        row.get("item_id", ""): parse_cell(row.get(value_column, ""), line)
        for line, row in enumerate(table.rows, start=2)
    }


def _parse_label(raw: str, line: int) -> bool:
    """The label vocabulary is strictly ``true``/``false`` (case-insensitive): a
    typo silently coerced to False is exactly the failure calibration exists to
    catch."""
    norm = raw.strip().lower()
    if norm not in {"true", "false"}:
        raise ValueError(
            f"{store.GOLD_CSV} line {line}: label must be true or false, got {raw!r}"
        )
    return norm == "true"


def _read_gold_labels(topic: store.Topic) -> dict[str, bool]:
    """Parse ``data/gold.csv`` into item_id -> label (strictly true/false)."""
    return _read_gold(topic, "label", _parse_label)


def _ineligible(n: int, reason: str | None = None) -> dict[str, Any]:
    """The conformal block for a pass that hasn't earned an interval."""
    return {
        "status": "ineligible",
        "reason": reason or f"n={n} < {calibration.MIN_CALIBRATION_N}",
        "n": n,
        "required": calibration.MIN_CALIBRATION_N,
    }


def _conformal_thresholds(pairs: list[tuple[float, bool]]) -> dict[str, Any]:
    """Split-conformal 90% prediction-set thresholds over (p, label) pairs."""
    if len(pairs) < calibration.MIN_CALIBRATION_N:
        return _ineligible(len(pairs))
    q_hat = calibration.conformal_quantile(
        calibration.binary_scores(pairs), calibration.ALPHA
    )
    return {
        "status": "ok",
        "n": len(pairs),
        "alpha": calibration.ALPHA,
        "quantile": round(q_hat, 4),
        "threshold_true": round(1.0 - q_hat, 4),
        "threshold_false": round(q_hat, 4),
    }


def _calibrate_probabilities(
    topic: store.Topic, *, mode: str, item_kind: str, scored: dict[str, float]
) -> ScoreReport:
    """Reliability check of a mode's per-item probabilities against gold labels."""
    gold = _read_gold_labels(topic)
    if not gold:
        raise ValueError(
            f"{store.GOLD_CSV} has no rows yet; add item_id,label rows "
            f"(label true/false) for the {item_kind} items you've judged, "
            "or omit the file until you have some."
        )
    unknown = sorted(set(gold) - set(scored))
    if unknown:
        raise ValueError(
            f"{store.GOLD_CSV}: unknown {item_kind} id(s): {', '.join(unknown)}"
        )
    pairs = [(scored[i], label) for i, label in gold.items()]
    report = calibration.reliability(pairs)
    conformal = _conformal_thresholds(pairs)

    header = f"{'bin':<11} {'n':>4} {'mean p':>8} {'hit rate':>9}"
    table = [
        f"calibration ({mode}): {report.n} gold label(s) "
        f"over {len(scored)} scored {item_kind}(s)",
        f"ECE {report.ece:.4f} | Brier {report.brier:.4f}",
        header,
        "-" * len(header),
    ]
    for b in report.bins:
        close = "]" if b.upper >= 1.0 else ")"
        mean_p = f"{b.mean_probability:.2f}" if b.mean_probability is not None else "-"
        hit = f"{b.hit_rate:.2f}" if b.hit_rate is not None else "-"
        table.append(
            f"[{b.lower:.1f},{b.upper:.1f}{close} {b.n:>4} {mean_p:>8} {hit:>9}"
        )
    if report.n < calibration.MIN_CALIBRATION_N:
        table.append(
            f"note: only {report.n} gold label(s) "
            f"(< {calibration.MIN_CALIBRATION_N}); treat these numbers as directional"
        )
    if conformal["status"] == "ok":
        table.append(
            f"conformal ({1 - calibration.ALPHA:.0%} coverage): "
            f"true when p >= {conformal['threshold_true']}, "
            f"false when p <= {conformal['threshold_false']} "
            f"(quantile {conformal['quantile']}, n={conformal['n']})"
        )
    else:
        table.append(f"conformal: ineligible ({conformal['reason']})")

    envelope: dict[str, Any] = {
        "topic": topic.config.title,
        "mode": mode,
        "item_kind": item_kind,
        "n_scored": len(scored),
        "n_gold": report.n,
        "ece": report.ece,
        "brier": report.brier,
        "bins": [
            {
                "lower": b.lower,
                "upper": b.upper,
                "n": b.n,
                "mean_probability": b.mean_probability,
                "hit_rate": b.hit_rate,
            }
            for b in report.bins
        ],
        "conformal": conformal,
    }
    return ScoreReport(table=table, envelope=envelope)


def calibrate_map(topic: store.Topic) -> ScoreReport:
    """`map`: per-category confidence vs a human genuinely-supported label."""
    scored = {r.category_id: r.confidence for r in map_rows(topic)}
    return _calibrate_probabilities(
        topic, mode="map", item_kind="category", scored=scored
    )


def calibrate_verify(topic: store.Topic) -> ScoreReport:
    """`verify`: per-claim certainty vs a human actually-true label."""
    scored = {v.claim_id: v.certainty / 100.0 for v in verify_rows(topic)}
    return _calibrate_probabilities(
        topic, mode="verify", item_kind="claim", scored=scored
    )


def calibrate_rank(topic: store.Topic) -> ScoreReport:
    """`rank`: per-cell certainty vs a human criterion-actually-met label."""
    scored = {
        # Cell id convention: <candidate_id>--<criterion_id>, as in evidence.csv.
        f"{v.candidate_id}{CELL_SEP}{s.criterion_id}": s.certainty / 100.0
        for v in rank_rows(topic)
        for s in v.criteria
    }
    return _calibrate_probabilities(topic, mode="rank", item_kind="cell", scored=scored)


def _parse_actual(raw: str, line: int) -> float:
    """A realized factor value: a positive number (log-space residuals have no
    logarithm otherwise)."""
    stripped = raw.strip()
    try:
        value = float(stripped)
    except ValueError:
        raise ValueError(
            f"{store.GOLD_CSV} line {line}: actual must be a number, got {stripped!r}"
        ) from None
    if value <= 0.0:
        raise ValueError(
            f"{store.GOLD_CSV} line {line}: actual must be positive, got {stripped!r}"
        )
    return value


def _read_gold_actuals(topic: store.Topic) -> dict[str, float]:
    """Parse estimate's ``data/gold.csv`` into factor_id -> realized value."""
    return _read_gold(topic, "actual", _parse_actual)


def calibrate_estimate(topic: store.Topic) -> ScoreReport:
    """`estimate`: conformalize the propagated interval from factor actuals.

    Data-gated twice: the analytic (pure product/quotient) path only — a
    mixed additive total is not lognormal, so a single log-space quantile
    would claim coverage it doesn't have — and at least MIN_CALIBRATION_N
    labeled factors with sigma > 0 (a point factor makes no uncertainty
    claim to check; excluded ones are listed, not silently dropped).
    """
    result = estimate_result(topic)
    actuals = _read_gold_actuals(topic)
    stats_by_id = {s.factor_id: s for s in result.factors}
    unknown = sorted(set(actuals) - set(stats_by_id))
    if unknown:
        raise ValueError(
            f"{store.GOLD_CSV}: unknown factor id(s): {', '.join(unknown)}"
        )
    excluded = sorted(fid for fid in actuals if stats_by_id[fid].sigma <= 0.0)
    usable = {fid: a for fid, a in actuals.items() if stats_by_id[fid].sigma > 0.0}

    conformal: dict[str, Any]
    if result.method != magnitude.ANALYTIC:
        conformal = _ineligible(len(usable), "mixed additive structure")
    elif len(usable) < calibration.MIN_CALIBRATION_N:
        conformal = _ineligible(len(usable))
    else:
        scores = calibration.standardized_log_residuals([
            (stats_by_id[fid].mu, stats_by_id[fid].sigma, actual)
            for fid, actual in usable.items()
        ])
        q_hat = calibration.conformal_quantile(scores, calibration.ALPHA)
        low, high = calibration.conformal_log_interval(
            result.median, result.sigma_total, q_hat
        )
        conformal = {
            "status": "ok",
            "n": len(usable),
            "alpha": calibration.ALPHA,
            "quantile": round(q_hat, 4),
            "model": {
                "median": result.median,
                "low": result.low,
                "high": result.high,
                "ci": result.ci,
            },
            "low": low,
            "high": high,
            "excluded_point_factors": excluded,
        }

    table = [
        f"calibration (estimate): {len(usable)} usable actual(s) "
        f"over {len(result.factors)} factor(s)",
        f"model ({result.method}): {result.median:g}  "
        f"[{result.ci:.0f}% CI {result.low:g} .. {result.high:g}]",
    ]
    if excluded:
        table.append(f"excluded point factors (sigma 0): {', '.join(excluded)}")
    if conformal["status"] == "ok":
        table.append(
            f"conformal ({1 - calibration.ALPHA:.0%} coverage): "
            f"[{conformal['low']:g} .. {conformal['high']:g}] "
            f"(quantile {conformal['quantile']}, n={conformal['n']})"
        )
    else:
        table.append(f"conformal: ineligible ({conformal['reason']})")

    envelope: dict[str, Any] = {
        "topic": topic.config.title,
        "mode": "estimate",
        "conformal": conformal,
    }
    return ScoreReport(table=table, envelope=envelope)


# The calibration half of the mode registry: map/verify/rank check per-item
# probabilities against gold labels; estimate conformalizes its interval from
# factor actuals. `find` reports coverage rates, not probabilities, so it has
# no entry and `research calibrate` refuses it cleanly.
MODE_CALIBRATORS: dict[str, Scorer] = {
    "map": calibrate_map,
    "verify": calibrate_verify,
    "rank": calibrate_rank,
    "estimate": calibrate_estimate,
}

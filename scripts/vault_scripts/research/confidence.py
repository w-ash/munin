"""The v3 falsifiable confidence model, as pure functions.

Confidence is breadth-based and falsifiable: corroboration across distinct
units raises it, divergence lowers it, and the subtraction happens after the
cap so counter-evidence never saturates.

    confidence = max(0, min(cap, step x supporting_units) - step x diverging_units)

This module replaces the live spreadsheet formulas of the xlsx era. Confidence
is never stored; callers recompute it from the evidence rows on every run.
Math runs in integer basis points so tier thresholds never wobble on float
representation error.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# Category-id conventions shared with the store: a `-div` suffix marks a row
# whose unit contradicts the category definition (counts against confidence),
# `-ref` marks a deliberately excluded reference row, and VOID retires a row
# that failed audit. Only exact-id and `-div` rows enter the math.
VOID_ID = "VOID"
DIV_SUFFIX = "-div"
REF_SUFFIX = "-ref"

# Grid cell id convention shared by rank (``<candidate_id>--<criterion_id>``) and
# find (``<entity_id>--<attribute_id>``). Defined once here so the store, scorer,
# and per-mode engines that build or split cell ids never drift apart.
CELL_SEP = "--"

_BP = 10_000  # basis points per 1.0

_TIER_THRESHOLDS_BP = (
    (8_500, "High"),
    (6_500, "Medium-High"),
    (5_000, "Medium"),
)


@dataclass(frozen=True)
class ConfidenceParams:
    """Tunable model parameters; defaults suit a large unit population."""

    step: float = 0.10
    cap: float = 0.95
    # A category with no primary source cannot exceed this ceiling, so "High"
    # (>= 85%) always rests on at least one primary-tier source. Default 0.84
    # is the top of Medium-High. Only applied when the caller supplies the
    # primary-backed set to ``compute_all``.
    primary_ceiling: float = 0.84


@dataclass(frozen=True)
class CategoryConfidence:
    """Computed confidence for one taxonomy category."""

    category_id: str
    supporting_units: int
    diverging_units: int
    evidence_count: int  # supporting rows; a depth metric, not a confidence input
    confidence: float
    tier: str
    # False when the primary ceiling clamped this category (no primary source).
    # True when a primary source backs it, or the ceiling is not in effect.
    primary_backed: bool = True


def tier(confidence: float) -> str:
    """Map a confidence value to its tier label."""
    confidence_bp = round(confidence * _BP)
    for threshold_bp, label in _TIER_THRESHOLDS_BP:
        if confidence_bp >= threshold_bp:
            return label
    return "Low"


def compute_all(
    taxonomy_ids: Sequence[str],
    rows: Iterable[tuple[str, str]],
    params: ConfidenceParams | None = None,
    primary_backed: set[str] | None = None,
) -> list[CategoryConfidence]:
    """Compute confidence for every taxonomy id from (unit, category_id) rows.

    Supporting rows match a taxonomy id exactly; diverging rows carry the
    ``-div`` suffix. ``VOID`` and ``-ref`` rows never enter any count. Distinct
    units are exact canonical strings, and a unit that both supports and
    diverges counts in both columns.

    ``primary_backed`` is the set of category ids that have at least one
    primary source. A category outside it is capped at ``params.primary_ceiling``
    (the clamp applies to the supporting side, before divergence subtracts), so
    "High" always rests on a primary source. Pass ``None`` to disable the
    ceiling entirely (every category scores as before).
    """
    params = params or ConfidenceParams()
    step_bp = round(params.step * _BP)
    cap_bp = round(params.cap * _BP)
    ceiling_bp = round(params.primary_ceiling * _BP)

    supporting: dict[str, set[str]] = {cid: set() for cid in taxonomy_ids}
    diverging: dict[str, set[str]] = {cid: set() for cid in taxonomy_ids}
    row_counts: dict[str, int] = dict.fromkeys(taxonomy_ids, 0)

    for unit, category_id in rows:
        if category_id in supporting:
            supporting[category_id].add(unit)
            row_counts[category_id] += 1
        elif category_id.endswith(DIV_SUFFIX):
            base = category_id.removesuffix(DIV_SUFFIX)
            if base in diverging:
                diverging[base].add(unit)

    results: list[CategoryConfidence] = []
    for cid in taxonomy_ids:
        n_support = len(supporting[cid])
        n_diverge = len(diverging[cid])
        has_primary = primary_backed is None or cid in primary_backed
        effective_cap_bp = cap_bp if has_primary else min(cap_bp, ceiling_bp)
        confidence_bp = max(
            0, min(effective_cap_bp, step_bp * n_support) - step_bp * n_diverge
        )
        confidence = confidence_bp / _BP
        results.append(
            CategoryConfidence(
                category_id=cid,
                supporting_units=n_support,
                diverging_units=n_diverge,
                evidence_count=row_counts[cid],
                confidence=confidence,
                tier=tier(confidence),
                primary_backed=has_primary,
            )
        )
    return results

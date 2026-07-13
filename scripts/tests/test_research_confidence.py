"""Tests for the v3 falsifiable confidence model."""

import pytest

from vault_scripts.research.confidence import (
    CategoryConfidence,
    ConfidenceParams,
    compute_all,
    tier,
)


def one(results: list[CategoryConfidence], cid: str = "C1") -> CategoryConfidence:
    return next(r for r in results if r.category_id == cid)


def rows_for_units(units: list[str], cid: str = "C1") -> list[tuple[str, str]]:
    return [(u, cid) for u in units]


def test_empty_store() -> None:
    results = compute_all(["C1", "C2"], [])
    assert len(results) == 2
    for r in results:
        assert r.supporting_units == 0
        assert r.diverging_units == 0
        assert r.evidence_count == 0
        assert r.confidence == 0.0
        assert r.tier == "Low"


@pytest.mark.parametrize(
    ("n_units", "confidence", "expected_tier"),
    [
        (1, 0.10, "Low"),
        (2, 0.20, "Low"),
        (3, 0.30, "Low"),
        (4, 0.40, "Low"),
        (5, 0.50, "Medium"),
        (6, 0.60, "Medium"),
        (7, 0.70, "Medium-High"),
        (8, 0.80, "Medium-High"),
        (9, 0.90, "High"),
    ],
)
def test_ramp(n_units: int, confidence: float, expected_tier: str) -> None:
    rows = rows_for_units([f"Unit {i}" for i in range(n_units)])
    result = one(compute_all(["C1"], rows))
    assert result.confidence == confidence
    assert result.tier == expected_tier


@pytest.mark.parametrize("n_units", [10, 12, 40])
def test_cap(n_units: int) -> None:
    rows = rows_for_units([f"Unit {i}" for i in range(n_units)])
    result = one(compute_all(["C1"], rows))
    assert result.confidence == 0.95
    assert result.tier == "High"


def test_divergence_subtracts_after_cap() -> None:
    rows = rows_for_units([f"Unit {i}" for i in range(12)])
    rows.append(("Diverger", "C1-div"))
    result = one(compute_all(["C1"], rows))
    assert result.supporting_units == 12
    assert result.diverging_units == 1
    assert result.confidence == 0.85
    assert result.tier == "High"


def test_floor_at_zero() -> None:
    rows = [("Alpha", "C1"), ("B", "C1-div"), ("C", "C1-div"), ("D", "C1-div")]
    result = one(compute_all(["C1"], rows))
    assert result.confidence == 0.0
    assert result.tier == "Low"


def test_duplicate_rows_same_unit_count_once() -> None:
    rows = [("Alpha", "C1"), ("Alpha", "C1"), ("Alpha", "C1")]
    result = one(compute_all(["C1"], rows))
    assert result.supporting_units == 1
    assert result.evidence_count == 3
    assert result.confidence == 0.10


def test_div_distinct_counting() -> None:
    rows = [("Alpha", "C1"), ("Gamma", "C1-div"), ("Gamma", "C1-div")]
    result = one(compute_all(["C1"], rows))
    assert result.diverging_units == 1
    assert result.confidence == 0.0


def test_div_rows_never_support() -> None:
    rows = [("Alpha", "C1-div")]
    results = compute_all(["C1"], rows)
    result = one(results)
    assert result.supporting_units == 0
    assert result.evidence_count == 0
    assert result.diverging_units == 1
    # No phantom category appears for the suffixed id.
    assert [r.category_id for r in results] == ["C1"]


def test_void_rows_excluded() -> None:
    rows = [("Alpha", "C1"), ("Beta", "VOID"), ("Alpha", "VOID")]
    result = one(compute_all(["C1"], rows))
    assert result.supporting_units == 1
    assert result.evidence_count == 1
    assert result.diverging_units == 0


def test_ref_rows_excluded() -> None:
    rows = [("Alpha", "C1"), ("Beta", "C1-ref")]
    result = one(compute_all(["C1"], rows))
    assert result.supporting_units == 1
    assert result.evidence_count == 1
    assert result.diverging_units == 0


def test_same_unit_supports_and_diverges() -> None:
    rows = [("Alpha", "C1"), ("Alpha", "C1-div")]
    result = one(compute_all(["C1"], rows))
    assert result.supporting_units == 1
    assert result.diverging_units == 1
    assert result.confidence == 0.0


def test_tunable_params() -> None:
    params = ConfidenceParams(step=0.05, cap=0.90)
    rows = rows_for_units([f"Unit {i}" for i in range(30)])
    result = one(compute_all(["C1"], rows, params))
    assert result.confidence == 0.90
    rows.append(("Diverger", "C1-div"))
    result = one(compute_all(["C1"], rows, params))
    assert result.confidence == 0.85


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (0.85, "High"),
        (0.849, "Medium-High"),
        (0.65, "Medium-High"),
        (0.649, "Medium"),
        (0.50, "Medium"),
        (0.49, "Low"),
        (0.0, "Low"),
        (0.95, "High"),
    ],
)
def test_tier_boundaries(confidence: float, expected: str) -> None:
    assert tier(confidence) == expected


def test_primary_ceiling_clamps_without_primary() -> None:
    # 9 units would reach 0.90, but with no primary source the ceiling holds it.
    rows = rows_for_units([f"U{i}" for i in range(9)])
    result = one(compute_all(["C1"], rows, None, set()))
    assert result.confidence == 0.84
    assert result.tier == "Medium-High"
    assert result.primary_backed is False


def test_primary_source_lifts_above_ceiling() -> None:
    rows = rows_for_units([f"U{i}" for i in range(9)])
    result = one(compute_all(["C1"], rows, None, {"C1"}))
    assert result.confidence == 0.90
    assert result.tier == "High"
    assert result.primary_backed is True


def test_ceiling_applies_before_divergence() -> None:
    rows = rows_for_units([f"U{i}" for i in range(9)])
    rows.append(("Div", "C1-div"))
    result = one(compute_all(["C1"], rows, None, set()))
    # clamp to 0.84 first, then subtract one diverging step: 0.84 - 0.10.
    assert result.confidence == 0.74


def test_none_primary_arg_disables_ceiling() -> None:
    rows = rows_for_units([f"U{i}" for i in range(9)])
    result = one(compute_all(["C1"], rows))
    assert result.confidence == 0.90
    assert result.primary_backed is True


def test_custom_primary_ceiling() -> None:
    params = ConfidenceParams(primary_ceiling=0.50)
    rows = rows_for_units([f"U{i}" for i in range(9)])
    result = one(compute_all(["C1"], rows, params, set()))
    assert result.confidence == 0.50
    assert result.tier == "Medium"


def test_categories_without_evidence_present_with_zeros() -> None:
    rows = [("Alpha", "C1")]
    results = compute_all(["C1", "C2", "C3"], rows)
    assert [r.category_id for r in results] == ["C1", "C2", "C3"]
    assert one(results, "C2").confidence == 0.0
    assert one(results, "C3").evidence_count == 0

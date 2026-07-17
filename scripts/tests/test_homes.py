"""Unit tests for the ``homes`` rubric scorer. The math is fixed-input/fixed-output
(weighted averages on the 1-5 scale, the infeasible clamp, coverage on blanks), so the
computed floats are asserted with ``pytest.approx``. The write path reuses ``fm``'s
line-at-a-time patcher, so the end-to-end test also checks that scoring a home leaves
its other frontmatter lines (quoted date, quoted coordinates) byte-for-byte intact."""

from __future__ import annotations

import pytest

from vault_scripts import homes
from vault_scripts._types import Adjustment, Comp, Criterion, OfferRatios
from vault_scripts.homes import (
    HomesError,
    adjust_comp,
    compute_offers,
    load_adjustments,
    load_criteria,
    score_home,
    value_home,
)

# light(9) + storage(6) + view(5) = weight 20.
_CRITERIA = [
    Criterion(key="light", weight=9, label="Light"),
    Criterion(key="storage", weight=6, label="Storage"),
    Criterion(key="view", weight=5, label="View"),
]

# The Criteria.md hub as run_score / load_criteria read it.
_CRITERIA_NOTE = (
    "---\n"
    'created: "2026-07-12"\n'
    "criteria:\n"
    "  - key: light\n"
    "    weight: 9\n"
    '    label: "Light"\n'
    "  - key: storage\n"
    "    weight: 6\n"
    '    label: "Storage"\n'
    "  - key: view\n"
    "    weight: 5\n"
    '    label: "View"\n'
    "offer_ratio_low: 1.04\n"
    "offer_ratio_mid: 1.1\n"
    "offer_ratio_high: 1.18\n"
    "---\n"
    "body\n"
)

# A home with a quoted date + coordinates (must survive), one criterion with realizable
# upside (light 4→5, moderate) and two flat criteria, and blank computed fields.
_HOME = (
    "---\n"
    'created: "2026-07-12"\n'
    "tags:\n"
    "  - home\n"
    'address: "1442 Oak St, Berkeley, CA"\n'
    'coordinates: "37.86, -122.27"\n'
    "list_price: 1250000\n"
    "light_actual: 4\n"
    "light_potential: 5\n"
    "light_effort: moderate\n"
    "storage_actual: 3\n"
    "storage_potential: 3\n"
    "view_actual: 5\n"
    "view_potential: 5\n"
    "score_actual:\n"
    "score_potential:\n"
    "score_upside:\n"
    "reno_burden:\n"
    "est_offer_low:\n"
    "est_offer_mid:\n"
    "est_offer_high:\n"
    'scored_at: ""\n'
    "---\n"
    "\n"
    "# 1442 Oak St\n"
    "body line with a stray key: value that must be ignored\n"
)


# --- score_home: the weighted math ---


def test_score_home_weighted_actual_and_potential():
    meta = {
        "light_actual": 4,
        "light_potential": 5,
        "light_effort": "moderate",
        "storage_actual": 3,
        "storage_potential": 3,
        "view_actual": 5,
        "view_potential": 5,
    }
    s = score_home(meta, _CRITERIA)
    # (9*4 + 6*3 + 5*5) / 20 = 79/20
    assert s.score_actual == pytest.approx(3.95)
    # (9*5 + 6*3 + 5*5) / 20 = 88/20
    assert s.score_potential == pytest.approx(4.40)
    assert s.score_upside == pytest.approx(0.45)
    # only light has upside: effort moderate (rank 2), weight 9 → 18/9
    assert s.reno_burden == pytest.approx(2.0)
    assert (s.rated, s.total) == (3, 3)


def test_score_home_infeasible_clamps_potential():
    meta = {
        "light_actual": 4,
        "light_potential": 5,
        "light_effort": "infeasible",  # upside can't be realized → clamp to 4
        "storage_actual": 3,
        "storage_potential": 3,
        "view_actual": 5,
        "view_potential": 5,
    }
    s = score_home(meta, _CRITERIA)
    assert s.score_actual == pytest.approx(3.95)
    assert s.score_potential == pytest.approx(3.95)  # clamped: equals actual
    assert s.score_upside == pytest.approx(0.0)
    assert s.reno_burden is None  # no realizable upside anywhere


def test_score_home_blank_criterion_drops_from_average():
    meta = {
        "light_actual": 4,
        "light_potential": 5,
        "light_effort": "moderate",
        "storage_actual": 3,
        "storage_potential": 3,
        # view unrated → excluded from numerator AND denominator
    }
    s = score_home(meta, _CRITERIA)
    # (9*4 + 6*3) / (9+6) = 54/15
    assert s.score_actual == pytest.approx(3.6)
    assert (s.rated, s.total) == (2, 3)


def test_score_home_blank_potential_defaults_to_actual():
    meta = {
        "light_actual": 4,  # no potential, no effort
        "storage_actual": 3,
        "storage_potential": 3,
        "view_actual": 5,
        "view_potential": 5,
    }
    s = score_home(meta, _CRITERIA)
    assert s.score_actual == pytest.approx(3.95)
    assert s.score_potential == pytest.approx(3.95)
    assert s.reno_burden is None


def test_score_home_unrated_returns_none():
    s = score_home({}, _CRITERIA)
    assert s.score_actual is None
    assert s.score_potential is None
    assert (s.rated, s.total) == (0, 3)


# --- compute_offers ---


def test_compute_offers_multiplies_list_price():
    ratios = OfferRatios(low=1.04, mid=1.10, high=1.18)
    assert compute_offers(1_250_000, ratios) == (1_300_000, 1_375_000, 1_475_000)


def test_compute_offers_skips_when_missing():
    full = OfferRatios(low=1.04, mid=1.10, high=1.18)
    assert compute_offers(None, full) is None
    assert compute_offers(1_250_000, OfferRatios(low=None, mid=1.1, high=1.2)) is None


# --- load_criteria ---


def test_load_criteria_parses_weights_and_ratios(tmp_path):
    p = tmp_path / "Criteria.md"
    p.write_text(_CRITERIA_NOTE, encoding="utf-8")
    criteria, ratios = load_criteria(p)
    assert [c.key for c in criteria] == ["light", "storage", "view"]
    assert [c.weight for c in criteria] == [9.0, 6.0, 5.0]
    assert ratios.low == pytest.approx(1.04)
    assert ratios.high == pytest.approx(1.18)


def test_load_criteria_missing_list_raises(tmp_path):
    p = tmp_path / "Criteria.md"
    p.write_text("---\nfoo: bar\n---\nbody\n", encoding="utf-8")
    with pytest.raises(HomesError):
        load_criteria(p)


def test_load_criteria_duplicate_key_raises(tmp_path):
    p = tmp_path / "Criteria.md"
    p.write_text(
        "---\ncriteria:\n"
        "  - key: light\n    weight: 9\n"
        "  - key: light\n    weight: 4\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(HomesError):
        load_criteria(p)


def test_load_criteria_missing_weight_raises(tmp_path):
    p = tmp_path / "Criteria.md"
    p.write_text(
        "---\ncriteria:\n  - key: light\n    label: Light\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(HomesError):
        load_criteria(p)


# --- run_score: end-to-end write + preservation (monkeypatched vault) ---


def _make_vault(tmp_path, home_text, criteria_note=_CRITERIA_NOTE):
    # Derive the tracker paths from the module constants so the helper follows the
    # tracker wherever it lives (currently Projects/Home Search/Homes/).
    criteria = tmp_path / homes._CRITERIA_REL
    entries = tmp_path / homes._ENTRIES_REL
    entries.mkdir(parents=True)
    criteria.write_text(criteria_note, encoding="utf-8")
    home = entries / "home1.md"
    home.write_text(home_text, encoding="utf-8")
    return home


def test_run_score_writes_and_preserves(tmp_path, monkeypatch):
    monkeypatch.setattr(homes, "VAULT", tmp_path)
    home = _make_vault(tmp_path, _HOME)
    res = homes.run_score([], write=True, scored_at="2026-07-12")

    assert res["written"] is True
    assert res["summary"]["scored"] == 1
    assert res["summary"]["skipped_offers"] == 0

    out = home.read_text(encoding="utf-8")
    # Untouched lines keep their exact quoting.
    assert 'created: "2026-07-12"' in out
    assert 'coordinates: "37.86, -122.27"' in out
    # Computed scalars written bare; scored_at quoted.
    assert "score_actual: 3.95\n" in out
    assert "score_potential: 4.4\n" in out
    assert "score_upside: 0.45\n" in out
    assert "reno_burden: 2\n" in out
    assert "est_offer_low: 1300000\n" in out
    assert "est_offer_mid: 1375000\n" in out
    assert "est_offer_high: 1475000\n" in out
    assert 'scored_at: "2026-07-12"' in out
    # A body line that looks like a field is never touched.
    assert "body line with a stray key: value that must be ignored" in out


def test_run_score_dry_run_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setattr(homes, "VAULT", tmp_path)
    home = _make_vault(tmp_path, _HOME)
    res = homes.run_score([], write=False, scored_at="2026-07-12")

    assert res["dryRun"] is True
    assert res["written"] is False
    assert res["summary"]["changed"] == 1
    # Field is still blank on disk (dry run).
    assert "score_actual: 3.95" not in home.read_text(encoding="utf-8")


def test_run_score_skips_offers_without_ratios(tmp_path, monkeypatch):
    note_no_ratios = (
        "---\ncriteria:\n"
        "  - key: light\n    weight: 9\n"
        "  - key: storage\n    weight: 6\n"
        "  - key: view\n    weight: 5\n---\nbody\n"
    )
    monkeypatch.setattr(homes, "VAULT", tmp_path)
    _make_vault(tmp_path, _HOME, criteria_note=note_no_ratios)
    res = homes.run_score([], write=False, scored_at="2026-07-12")

    assert res["summary"]["scored"] == 1
    assert res["summary"]["skipped_offers"] == 1
    assert res["homes"][0]["est_offer_mid"] is None


# --- valuation: the adjustment schedule ---

_ADJ_NOTE = (
    "---\n"
    'created: "2026-07-12"\n'
    "adjustments:\n"
    "  - feature: sqft\n"
    "    unit: per_sqft\n"
    "    low: 150\n"
    "    mid: 200\n"
    "    high: 300\n"
    "    basis: hedonic\n"
    "  - feature: baths\n"
    "    unit: each\n"
    "    mid: 20000\n"
    "  - feature: beds\n"
    "    unit: each\n"
    "    mid: 25000\n"
    "---\n"
    "body\n"
)


def _sched():
    return [
        Adjustment(feature="sqft", unit="per_sqft", low=150, mid=200, high=300),
        Adjustment(feature="baths", unit="each", low=15000, mid=20000, high=25000),
        Adjustment(feature="beds", unit="each", low=20000, mid=25000, high=30000),
    ]


def _mk_comp(**over):
    base = {
        "subject": "home1",
        "address": "comp",
        "sale_price": 1_000_000.0,
        "sale_date": "2026-01-01",
        "beds": 3.0,
        "baths": 2.0,
        "sqft": 1800.0,
        "lot_sqft": 4000.0,
        "year_built": 1920,
        "dist_mi": 0.0,
        "garage": None,
        "adu": None,
        "condition": None,
        "source": "manual",
        "source_id": "c1",
    }
    base.update(over)
    return Comp(**base)


def test_load_adjustments_parses(tmp_path):
    p = tmp_path / "Adjustments.md"
    p.write_text(_ADJ_NOTE, encoding="utf-8")
    adj = load_adjustments(p)
    assert [a.feature for a in adj] == ["sqft", "baths", "beds"]
    sqft = adj[0]
    assert sqft.mid == pytest.approx(200)
    assert sqft.low == pytest.approx(150)
    assert sqft.basis == "hedonic"
    # low/high default to mid when absent.
    baths = adj[1]
    assert baths.low == pytest.approx(20000)
    assert baths.high == pytest.approx(20000)


def test_load_adjustments_missing_list_raises(tmp_path):
    p = tmp_path / "Adjustments.md"
    p.write_text("---\nfoo: bar\n---\nbody\n", encoding="utf-8")
    with pytest.raises(HomesError):
        load_adjustments(p)


def test_load_adjustments_missing_mid_raises(tmp_path):
    p = tmp_path / "Adjustments.md"
    p.write_text(
        "---\nadjustments:\n  - feature: sqft\n    unit: per_sqft\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(HomesError):
        load_adjustments(p)


def test_load_adjustments_duplicate_feature_raises(tmp_path):
    p = tmp_path / "Adjustments.md"
    p.write_text(
        "---\nadjustments:\n"
        "  - feature: sqft\n    mid: 200\n"
        "  - feature: sqft\n    mid: 300\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(HomesError):
        load_adjustments(p)


# --- valuation: the comp-adjustment grid ---


def test_adjust_comp_adds_scheduled_dollars():
    schedule = {a.feature: a for a in _sched()}
    subject = {"sqft": 2000.0, "beds": 3.0, "baths": 2.0}
    comp = _mk_comp(sale_price=1_000_000.0, sqft=1800.0, beds=3.0, baths=2.0)
    ca = adjust_comp(subject, comp, schedule, 2026)
    assert ca is not None
    # only sqft differs: (2000 - 1800) * 200 = +40,000
    assert ca.adjustments == pytest.approx({"sqft": 40000})
    assert ca.adjusted_price == pytest.approx(1_040_000)


def test_adjust_comp_skips_comp_without_sale_price():
    schedule = {a.feature: a for a in _sched()}
    comp = _mk_comp(sale_price=None)
    assert adjust_comp({"sqft": 2000.0}, comp, schedule, 2026) is None


def test_value_home_reconciles_adjusted_comps():
    comp_a = _mk_comp(sale_price=1_000_000.0, sqft=1800.0, beds=3.0, baths=2.0)
    comp_b = _mk_comp(sale_price=1_100_000.0, sqft=2000.0, beds=3.0, baths=1.0)
    v = value_home(
        {"sqft": 2000, "beds": 3, "baths": 2},
        [comp_a, comp_b],
        _sched(),
        OfferRatios(low=1.04, mid=1.10, high=1.18),
        1_000_000,
        2026,
    )
    # a → 1,040,000 (sqft +40k); b → 1,120,000 (baths +20k); equal weights → mean.
    assert v.basis == "comps"
    assert v.predicted_price == 1_080_000
    assert v.comps_used == 2
    assert v.implied_over_list == pytest.approx(1.08)
    assert v.confidence == "low"  # n=2 < _MIN_COMPS
    assert v.predicted_low < v.predicted_price < v.predicted_high


def test_value_home_falls_back_to_prior_without_comps():
    v = value_home(
        {"sqft": 2000},
        [],
        _sched(),
        OfferRatios(low=1.0, mid=1.1, high=1.2),
        1_000_000,
        2026,
    )
    assert v.basis == "prior"
    assert v.comps_used == 0
    assert v.predicted_price == 1_100_000
    assert v.predicted_low == 1_000_000
    assert v.predicted_high == 1_200_000


# --- run_value: end-to-end write + preservation + idempotency ---

_VALUE_HOME = (
    "---\n"
    'created: "2026-07-12"\n'
    "tags:\n"
    "  - home\n"
    'address: "500 Test St, Berkeley, CA"\n'
    'coordinates: "37.87, -122.27"\n'
    "list_price: 1000000\n"
    "beds: 3\n"
    "baths: 2\n"
    "sqft: 2000\n"
    "predicted_price:\n"
    "predicted_low:\n"
    "predicted_high:\n"
    "implied_over_list:\n"
    'valuation_confidence: ""\n'
    "comps_used:\n"
    'valued_at: ""\n'
    "---\n"
    "\n"
    "# 500 Test St\n"
    "\n"
    "## Notes\n"
    "\n"
    "Some notes.\n"
)

_COMPS_HEADER = (
    "subject,address,sale_price,sale_date,beds,baths,sqft,lot_sqft,"
    "year_built,dist_mi,garage,adu,condition,source,source_id\n"
)
# Equal distance (0) and same-year sales → equal weights → exact reconciled mean.
_COMPS_TWO = _COMPS_HEADER + (
    "home1,100 A St,1000000,2026-01-01,3,2,1800,4000,1920,0,,,,manual,m1\n"
    "home1,200 B St,1100000,2026-01-01,3,1,2000,4200,1930,0,,,,manual,m2\n"
)


def _make_value_vault(tmp_path, home_text, comps_csv):
    # Derive every tracker path from the module constants (see _make_vault).
    criteria = tmp_path / homes._CRITERIA_REL
    adjustments = tmp_path / homes._ADJUSTMENTS_REL
    comps = tmp_path / homes.COMPS_REL
    entries = tmp_path / homes._ENTRIES_REL
    entries.mkdir(parents=True)
    comps.parent.mkdir(parents=True, exist_ok=True)
    criteria.write_text(_CRITERIA_NOTE, encoding="utf-8")
    adjustments.write_text(_ADJ_NOTE, encoding="utf-8")
    comps.write_text(comps_csv, encoding="utf-8")
    home = entries / "home1.md"
    home.write_text(home_text, encoding="utf-8")
    return home


def test_run_value_writes_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(homes, "VAULT", tmp_path)
    home = _make_value_vault(tmp_path, _VALUE_HOME, _COMPS_TWO)
    res = homes.run_value([], write=True, valued_at="2026-07-12", now_year=2026)

    assert res["written"] is True
    assert res["summary"]["valued"] == 1
    assert res["homes"][0]["basis"] == "comps"

    out = home.read_text(encoding="utf-8")
    # Untouched frontmatter lines keep their exact quoting.
    assert 'created: "2026-07-12"' in out
    assert 'coordinates: "37.87, -122.27"' in out
    # Computed scalars + the body table are written.
    assert "predicted_price: 1080000\n" in out
    assert "valuation_confidence:" in out
    assert 'valued_at: "2026-07-12"' in out
    assert "## Valuation" in out
    assert "| Comp | Sold | Sale price |" in out

    # Re-running with the same inputs must leave the note byte-for-byte identical.
    homes.run_value([], write=True, valued_at="2026-07-12", now_year=2026)
    assert home.read_text(encoding="utf-8") == out


def test_run_value_dry_run_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setattr(homes, "VAULT", tmp_path)
    home = _make_value_vault(tmp_path, _VALUE_HOME, _COMPS_TWO)
    res = homes.run_value([], write=False, valued_at="2026-07-12", now_year=2026)
    assert res["dryRun"] is True
    assert res["written"] is False
    assert "predicted_price: 1080000" not in home.read_text(encoding="utf-8")


def test_run_value_prior_fallback_without_comps(tmp_path, monkeypatch):
    monkeypatch.setattr(homes, "VAULT", tmp_path)
    home = _make_value_vault(tmp_path, _VALUE_HOME, _COMPS_HEADER)
    res = homes.run_value([], write=True, valued_at="2026-07-12", now_year=2026)
    assert res["homes"][0]["basis"] == "prior"
    assert res["summary"]["prior_fallback"] == 1
    out = home.read_text(encoding="utf-8")
    # Prior band = list_price * the Criteria.md ratios (mid 1.1 here).
    assert "predicted_price: 1100000\n" in out
    assert "(prior)" in out

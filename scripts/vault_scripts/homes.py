"""Weighted actual-vs-potential rubric scorer for the Homes tracker.

The Homes tracker is project-scoped: it lives under ``Projects/Home Search/Homes/``
(a bounded home-buying project), not as a root-level life domain. Each candidate
home in ``Projects/Home Search/Homes/entries/`` scores every criterion twice, current
``<key>_actual`` and post-renovation ``<key>_potential`` (both 1-5), plus a
``<key>_effort`` marker (easy/moderate/major/infeasible). The shared criteria and
their weights live once in ``Projects/Home Search/Homes/Criteria.md``; this scorer reads them, computes
weighted averages on the 1-5 scale, and writes four numbers back onto each home:

- ``score_actual``   = Σ(weight × actual) / Σ(weight)
- ``score_potential``= same, but ``potential`` clamped to ``actual`` where effort is
  ``infeasible`` (upside you can't realize doesn't inflate the number)
- ``score_upside``   = score_potential − score_actual
- ``reno_burden``    = weighted mean of effort rank over criteria with realizable upside

Blank criteria drop out of that home's average (numerator and denominator), so a
partly-toured house isn't scored as if the blank were a zero; coverage is reported.
When ``Projects/Home Search/Homes/Criteria.md`` carries an offer ratio band (from the ``berkeley-offer-model``
estimate topic) and the home has a ``list_price``, it also fills ``est_offer_{low,mid,high}``.

Writes go one line at a time through :mod:`vault_scripts._utils` (the same path
``vault-tool fm`` uses), leaving every other line byte-for-byte intact. Dry-run by
default; pass ``--write`` to persist. A batch that hits a home with no frontmatter
writes nothing (all-or-nothing).

Usage:
    scripts/vault-tool homes score [PATH ...] [--write]

Examples:
    # preview scores for every home (dry run)
    scripts/vault-tool homes score

    # score and persist just one home
    scripts/vault-tool homes score "Projects/Home Search/Homes/entries/2117 Grant St.md" --write
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import datetime as _dt
import json
import math
from pathlib import Path
import sys
from typing import cast

import frontmatter
import yaml

from vault_scripts._comps import (
    COMPS_REL,
    append_comps,
    fetch_comps,
    load_comps,
    subject_slug,
)
from vault_scripts._retry import APIError
from vault_scripts._types import (
    Adjustment,
    Comp,
    CompAdjustment,
    Criterion,
    HomeScore,
    HomeValuation,
    OfferRatios,
)
from vault_scripts._utils import (
    VAULT,
    find_vault_file,
    fm_str,
    parse_typed_args,
    patch_field,
    rel_path,
    require_env,
    upsert_section,
)

_CRITERIA_REL = "Projects/Home Search/Homes/Criteria.md"
_ADJUSTMENTS_REL = "Projects/Home Search/Homes/Adjustments.md"
_ENTRIES_REL = "Projects/Home Search/Homes/entries"

# Effort → burden rank. ``infeasible`` is absent by design: it clamps potential to
# actual (no realizable upside), so it never enters the burden average.
_EFFORT_RANK: dict[str, int] = {"easy": 1, "moderate": 2, "major": 3}

# Precision for written score scalars.
_DP = 2

# --- valuation tuning (transparent v1; Phase 5 back-testing calibrates these) ---
# Objective feature: the subject frontmatter key and Comp attribute share the
# name. A feature is adjusted only when present on BOTH subject and comp; every
# adjustment is mid * (subject_value - comp_value); see the Adjustment docstring.
_FEATURE_KEYS: tuple[str, ...] = (
    "beds",
    "baths",
    "sqft",
    "lot_sqft",
    "year_built",
    "garage",
    "adu",
    "condition",
)
# Fewer than this many usable comps: low confidence and a widened band.
_MIN_COMPS = 3
# z for a 90% normal interval (predicted +/- z*spread).
_Z90 = 1.645
# Multiply the spread when comps are thin.
_THIN_WIDEN = 1.5
# Relative dispersion (spread / estimate) above this drops confidence to medium.
_HIGH_DISPERSION = 0.12
# Floor the band at z*this*estimate so a single/zero-variance comp still
# reports real uncertainty instead of a false-precision point.
_MIN_BAND_FRAC = 0.04
# Comp similarity: a comp's weight halves every _RECENCY_HALFLIFE_YEARS of age.
_RECENCY_HALFLIFE_YEARS = 2.0
# Precision for the written over/under-list ratio.
_RATIO_DP = 3


class _Args(argparse.Namespace):
    command: str
    paths: list[str]
    write: bool
    # comps subcommand (unset on score/value; class defaults avoid AttributeError)
    comps_command: str | None = None
    file: str | None = None
    count: int = 15


@dataclass
class _HomePlan:
    """One home's planned edit: the report shown to the caller, the rewritten text
    (``None`` when the note has no frontmatter and is skipped), and whether it changed."""

    fp: Path
    report: dict[str, object]
    new_text: str | None
    changed: bool


class HomesError(Exception):
    """User-facing input error (missing criteria note, bad weight, missing file)."""


# --- value coercion ---


def _as_num(value: object) -> float | None:
    """Coerce a frontmatter value to a float, or None when absent/blank/non-numeric.
    Bools are rejected (a YAML ``true`` is not a score)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _as_effort(value: object) -> str:
    """Normalize an effort marker to a lowercase string ("" when absent)."""
    return value.strip().lower() if isinstance(value, str) else ""


# --- pure scoring ---


def load_criteria(path: Path) -> tuple[list[Criterion], OfferRatios]:
    """Parse the shared criteria list and offer ratios from ``Projects/Home Search/Homes/Criteria.md``.

    Raises :class:`HomesError` on a missing/malformed ``criteria`` list, a criterion
    without a key or numeric weight, or a duplicate key.
    """
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    meta = post.metadata
    raw = meta.get("criteria")
    if not isinstance(raw, list):
        raise HomesError(f"{path.name}: missing or malformed 'criteria' list in frontmatter")
    items = cast("list[object]", raw)
    criteria: list[Criterion] = []
    seen: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise HomesError(f"{path.name}: criteria[{i}] is not a mapping")
        entry = cast("dict[str, object]", item)
        key = entry.get("key")
        weight = _as_num(entry.get("weight"))
        if not isinstance(key, str) or not key:
            raise HomesError(f"{path.name}: criteria[{i}] missing a string 'key'")
        if weight is None:
            raise HomesError(f"{path.name}: criterion '{key}' missing a numeric 'weight'")
        if key in seen:
            raise HomesError(f"{path.name}: duplicate criterion key '{key}'")
        seen.add(key)
        label = entry.get("label", "")
        criteria.append(Criterion(key=key, weight=weight, label=str(label)))
    ratios = OfferRatios(
        low=_as_num(meta.get("offer_ratio_low")),
        mid=_as_num(meta.get("offer_ratio_mid")),
        high=_as_num(meta.get("offer_ratio_high")),
    )
    return criteria, ratios


def load_adjustments(path: Path) -> list[Adjustment]:
    """Parse the feature adjustment schedule from ``Projects/Home Search/Homes/Adjustments.md``.

    Each ``adjustments`` frontmatter entry needs a string ``feature`` and a numeric
    ``mid`` (dollars per one unit of that feature's difference); ``low``/``high``
    default to ``mid`` when absent, and ``unit``/``basis``/``source`` are optional
    provenance. Raises :class:`HomesError` on a missing/malformed list, an entry
    without a feature or ``mid``, or a duplicate feature.
    """
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    raw = post.metadata.get("adjustments")
    if not isinstance(raw, list):
        raise HomesError(
            f"{path.name}: missing or malformed 'adjustments' list in frontmatter"
        )
    items = cast("list[object]", raw)
    out: list[Adjustment] = []
    seen: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise HomesError(f"{path.name}: adjustments[{i}] is not a mapping")
        entry = cast("dict[str, object]", item)
        feature = entry.get("feature")
        mid = _as_num(entry.get("mid"))
        if not isinstance(feature, str) or not feature:
            raise HomesError(f"{path.name}: adjustments[{i}] missing a string 'feature'")
        if mid is None:
            raise HomesError(f"{path.name}: adjustment '{feature}' missing a numeric 'mid'")
        if feature in seen:
            raise HomesError(f"{path.name}: duplicate adjustment feature '{feature}'")
        seen.add(feature)
        low = _as_num(entry.get("low"))
        high = _as_num(entry.get("high"))
        out.append(
            Adjustment(
                feature=feature,
                unit=str(entry.get("unit", "")),
                low=low if low is not None else mid,
                mid=mid,
                high=high if high is not None else mid,
                basis=str(entry.get("basis", "")),
                source=str(entry.get("source", "")),
            )
        )
    return out


def score_home(metadata: Mapping[str, object], criteria: Sequence[Criterion]) -> HomeScore:
    """Compute the weighted actual/potential scores for one home's frontmatter.

    Criteria with no ``<key>_actual`` value are skipped entirely (they don't count
    toward the average either way). ``infeasible`` effort clamps potential to actual.
    Returns all-``None`` scores when the home has no rated criteria.
    """
    sum_w = sum_wa = sum_wp = 0.0
    burden_w = burden_wr = 0.0
    rated = 0
    for c in criteria:
        actual = _as_num(metadata.get(f"{c.key}_actual"))
        if actual is None:
            continue
        rated += 1
        potential = _as_num(metadata.get(f"{c.key}_potential"))
        effort = _as_effort(metadata.get(f"{c.key}_effort"))
        if potential is None or effort == "infeasible":
            used = actual
        else:
            used = max(actual, potential)
        sum_w += c.weight
        sum_wa += c.weight * actual
        sum_wp += c.weight * used
        if used > actual and effort in _EFFORT_RANK:
            burden_w += c.weight
            burden_wr += c.weight * _EFFORT_RANK[effort]
    total = len(criteria)
    if rated == 0 or sum_w == 0:
        return HomeScore(None, None, None, None, 0, total)
    actual_score = round(sum_wa / sum_w, _DP)
    potential_score = round(sum_wp / sum_w, _DP)
    upside = round(potential_score - actual_score, _DP)
    burden = round(burden_wr / burden_w, _DP) if burden_w else None
    return HomeScore(actual_score, potential_score, upside, burden, rated, total)


def compute_offers(
    list_price: float | None, ratios: OfferRatios
) -> tuple[int, int, int] | None:
    """Per-home offer band = ``list_price × ratio`` for low/mid/high. None when the
    list price or any ratio is missing (the whole band is skipped, never partial)."""
    if list_price is None or ratios.low is None or ratios.mid is None or ratios.high is None:
        return None
    return (
        round(list_price * ratios.low),
        round(list_price * ratios.mid),
        round(list_price * ratios.high),
    )


# --- valuation: comp-adjustment grid ---


def _subject_features(metadata: Mapping[str, object]) -> dict[str, float]:
    """The subject's objective feature values, read from its frontmatter. Only
    keys actually present are returned, so a home missing (say) a ``garage`` field
    simply skips that adjustment rather than distorting the estimate."""
    feats: dict[str, float] = {}
    for key in _FEATURE_KEYS:
        value = _as_num(metadata.get(key))
        if value is not None:
            feats[key] = value
    return feats


def _comp_features(comp: Comp) -> dict[str, float]:
    """The comp's objective feature values, dropping any that are blank."""
    raw: dict[str, float | None] = {
        "beds": comp.beds,
        "baths": comp.baths,
        "sqft": comp.sqft,
        "lot_sqft": comp.lot_sqft,
        "year_built": float(comp.year_built) if comp.year_built is not None else None,
        "garage": float(comp.garage) if comp.garage is not None else None,
        "adu": float(comp.adu) if comp.adu is not None else None,
        "condition": float(comp.condition) if comp.condition is not None else None,
    }
    return {k: v for k, v in raw.items() if v is not None}


def _sale_year(sale_date: str) -> int | None:
    """The 4-digit year at the front of a ``YYYY-MM-DD`` sale date, or None."""
    head = sale_date.strip()[:4]
    return int(head) if head.isdigit() else None


def _comp_weight(comp: Comp, now_year: int) -> float:
    """A comp's reconciliation weight: nearer and more recent comps count more.
    Distance shrinks the weight as ``1/(1+miles)``; age halves it every
    ``_RECENCY_HALFLIFE_YEARS``. Missing distance/date leave that factor at 1."""
    weight = 1.0
    if comp.dist_mi is not None and comp.dist_mi >= 0:
        weight *= 1.0 / (1.0 + comp.dist_mi)
    year = _sale_year(comp.sale_date)
    if year is not None:
        age = max(now_year - year, 0)
        weight *= math.pow(0.5, age / _RECENCY_HALFLIFE_YEARS)
    return weight


def adjust_comp(
    subject: Mapping[str, float],
    comp: Comp,
    schedule: Mapping[str, Adjustment],
    now_year: int,
) -> CompAdjustment | None:
    """Move one comp's sale price toward the subject via the adjustment schedule.

    For every feature present on both, adds ``mid × (subject − comp)`` dollars.
    Returns None for a comp with no sale price (nothing to adjust)."""
    if comp.sale_price is None:
        return None
    comp_feats = _comp_features(comp)
    adjustments: dict[str, float] = {}
    total = 0.0
    for feature, adj in schedule.items():
        if feature not in subject or feature not in comp_feats:
            continue
        delta = subject[feature] - comp_feats[feature]
        if not delta:
            continue
        dollars = adj.mid * delta
        adjustments[feature] = dollars
        total += dollars
    return CompAdjustment(
        address=comp.address,
        sale_price=comp.sale_price,
        sale_date=comp.sale_date,
        adjustments=adjustments,
        adjusted_price=comp.sale_price + total,
        weight=_comp_weight(comp, now_year),
    )


def _reconcile(
    adjusteds: Sequence[CompAdjustment],
) -> tuple[float, float, float, str, str]:
    """Combine adjusted comps into a weighted point estimate and a 90% band.

    Returns ``(point, low, high, confidence, reason)``. The band comes from the
    weighted dispersion of the adjusted prices, floored so a lone comp still
    carries uncertainty and widened when comps are thin. Confidence drops on few
    comps or high dispersion.
    """
    prices = [ca.adjusted_price for ca in adjusteds]
    weights = [ca.weight for ca in adjusteds]
    total_w = sum(weights)
    if total_w <= 0:
        weights = [1.0] * len(adjusteds)
        total_w = float(len(adjusteds))
    point = sum(p * w for p, w in zip(prices, weights, strict=True)) / total_w
    variance = (
        sum(w * (p - point) ** 2 for p, w in zip(prices, weights, strict=True)) / total_w
    )
    spread = math.sqrt(variance)
    n = len(adjusteds)
    rel = spread / point if point else 0.0
    if n < _MIN_COMPS:
        confidence = "low"
        reason = f"thin comps (n={n} < {_MIN_COMPS}); band widened"
        spread *= _THIN_WIDEN
    elif rel > _HIGH_DISPERSION:
        confidence = "medium"
        reason = f"high comp dispersion ({rel:.0%} of estimate)"
    else:
        confidence = "high"
        reason = f"{n} comps, dispersion {rel:.0%}"
    spread = max(spread, point * _MIN_BAND_FRAC)
    return point, point - _Z90 * spread, point + _Z90 * spread, confidence, reason


def _prior_valuation(
    list_price: float | None, ratios: OfferRatios
) -> HomeValuation:
    """The fallback when no usable comps exist: the ``berkeley-offer-model`` ratio
    band applied to list price, flagged ``basis=prior`` at low confidence."""
    if (
        list_price is None
        or ratios.low is None
        or ratios.mid is None
        or ratios.high is None
    ):
        return HomeValuation(
            None, None, None, None, "low", "prior", 0,
            "no comps and no offer-ratio prior available", [],
        )
    return HomeValuation(
        predicted_price=round(list_price * ratios.mid),
        predicted_low=round(list_price * ratios.low),
        predicted_high=round(list_price * ratios.high),
        implied_over_list=round(ratios.mid, _RATIO_DP),
        confidence="low",
        basis="prior",
        comps_used=0,
        reason="no comps; using berkeley-offer-model ratio prior",
        breakdown=[],
    )


def value_home(
    metadata: Mapping[str, object],
    comps: Sequence[Comp],
    schedule: Sequence[Adjustment],
    ratios: OfferRatios,
    list_price: float | None,
    now_year: int,
) -> HomeValuation:
    """Predict one home's sale price from its comps and the adjustment schedule.

    Adjusts every comp toward the subject, reconciles the survivors to a point +
    90% band, and derives over/under-list from list price. Falls back to the ratio
    prior when no comp carries a usable sale price."""
    subject = _subject_features(metadata)
    schedule_map = {a.feature: a for a in schedule}
    adjusteds: list[CompAdjustment] = []
    for comp in comps:
        ca = adjust_comp(subject, comp, schedule_map, now_year)
        if ca is not None:
            adjusteds.append(ca)
    if not adjusteds:
        return _prior_valuation(list_price, ratios)
    point, low, high, confidence, reason = _reconcile(adjusteds)
    over = round(point / list_price, _RATIO_DP) if list_price else None
    return HomeValuation(
        predicted_price=round(point),
        predicted_low=round(low),
        predicted_high=round(high),
        implied_over_list=over,
        confidence=confidence,
        basis="comps",
        comps_used=len(adjusteds),
        reason=reason,
        breakdown=adjusteds,
    )


# --- file discovery + write planning ---


def _has_home_tag(post: frontmatter.Post) -> bool:
    raw = post.metadata.get("tags")
    if isinstance(raw, str):
        return raw == "home"
    if isinstance(raw, list):
        return "home" in cast("list[object]", raw)
    return False


def discover_home_files() -> list[Path]:
    """Every ``#home`` note under ``Projects/Home Search/Homes/entries/`` (sorted). Skips unreadable notes
    and anything not tagged ``home`` (the ``Criteria.md`` hub is not tagged, so it's
    excluded)."""
    entries = VAULT / _ENTRIES_REL
    if not entries.is_dir():
        return []
    files: list[Path] = []
    for p in sorted(entries.glob("*.md")):
        try:
            post = frontmatter.loads(p.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if _has_home_tag(post):
            files.append(p)
    return files


def _computed_fields(
    score: HomeScore, offers: tuple[int, int, int] | None, scored_at: str
) -> list[tuple[str, object]]:
    """The frontmatter fields to write back for one home, in note order. Empty when
    the home is unrated and has no offer band (nothing computed to write)."""
    fields: list[tuple[str, object]] = []
    if score.score_actual is not None:
        fields.extend([
            ("score_actual", score.score_actual),
            ("score_potential", score.score_potential),
            ("score_upside", score.score_upside),
        ])
    if score.reno_burden is not None:
        fields.append(("reno_burden", score.reno_burden))
    if offers is not None:
        fields.extend([
            ("est_offer_low", offers[0]),
            ("est_offer_mid", offers[1]),
            ("est_offer_high", offers[2]),
        ])
    if fields:
        fields.append(("scored_at", scored_at))
    return fields


def _plan_home(
    fp: Path,
    criteria: Sequence[Criterion],
    ratios: OfferRatios,
    scored_at: str,
) -> _HomePlan:
    """Read one home, compute its scores + offers, and fold the results into new text."""
    text = fp.read_text(encoding="utf-8")
    rel = str(rel_path(fp))
    if not text.startswith("---"):
        return _HomePlan(
            fp, {"path": rel, "error": "no frontmatter block", "changed": False}, None, False
        )
    post = frontmatter.loads(text)
    score = score_home(post.metadata, criteria)
    offers = compute_offers(_as_num(post.metadata.get("list_price")), ratios)
    fields = _computed_fields(score, offers, scored_at)
    new_text = text
    for name, value in fields:
        new_text = patch_field(new_text, name, value)
    changed = new_text != text
    report: dict[str, object] = {
        "path": rel,
        "changed": changed,
        "coverage": f"{score.rated}/{score.total}",
        "score_actual": score.score_actual,
        "score_potential": score.score_potential,
        "score_upside": score.score_upside,
        "reno_burden": score.reno_burden,
        "est_offer_low": offers[0] if offers else None,
        "est_offer_mid": offers[1] if offers else None,
        "est_offer_high": offers[2] if offers else None,
        "offers_skipped": offers is None,
        "unrated": score.score_actual is None,
    }
    return _HomePlan(fp, report, new_text, changed)


def run_score(paths: list[str], write: bool, scored_at: str) -> dict[str, object]:
    """Plan and (optionally) apply rubric scores across homes.

    With no ``paths``, scores every ``#home`` note under ``Projects/Home Search/Homes/entries/``. Computes
    every home's edit first; when ``write`` is set and no home errored, the whole batch
    is written (a single note with no frontmatter aborts the write so nothing lands
    half-done, matching ``fm``).
    """
    criteria_path = VAULT / _CRITERIA_REL
    if not criteria_path.exists():
        raise HomesError(f"criteria note not found: {_CRITERIA_REL}")
    criteria, ratios = load_criteria(criteria_path)
    total_weight = sum(c.weight for c in criteria)

    if paths:
        files: list[Path] = []
        missing: list[str] = []
        for p in paths:
            fp = find_vault_file(p)
            if fp is None:
                missing.append(p)
            else:
                files.append(fp)
        if missing:
            raise HomesError(f"file(s) not found: {', '.join(missing)}")
    else:
        files = discover_home_files()

    plans = [_plan_home(fp, criteria, ratios, scored_at) for fp in files]
    errored = [pl for pl in plans if "error" in pl.report]
    do_write = write and not errored
    if do_write:
        for pl in plans:
            if pl.changed and pl.new_text is not None:
                pl.fp.write_text(pl.new_text, encoding="utf-8")

    scored = sum(1 for pl in plans if not pl.report.get("unrated") and "error" not in pl.report)
    result: dict[str, object] = {
        "ok": not errored,
        "cmd": "homes score",
        "dryRun": not write,
        "written": do_write,
        "weights_source": _CRITERIA_REL,
        "total_weight": total_weight,
        "offer_ratio": {"low": ratios.low, "mid": ratios.mid, "high": ratios.high},
        "summary": {
            "homes": len(plans),
            "scored": scored,
            "unrated": sum(1 for pl in plans if pl.report.get("unrated")),
            "skipped_offers": sum(1 for pl in plans if pl.report.get("offers_skipped")),
            "changed": sum(1 for pl in plans if pl.changed),
            "errored": len(errored),
        },
        "homes": [pl.report for pl in plans],
    }
    if write and errored:
        result["aborted"] = "no files written: fix the errored homes above and retry"
    return result


# --- valuation write planning ---


def _dollars(value: float) -> str:
    return f"${round(value):,}"


def _signed_dollars(value: float) -> str:
    r = round(value)
    return f"+${r:,}" if r >= 0 else f"-${-r:,}"


def _pct_over(over: float | None) -> str:
    if over is None:
        return "n/a"
    pct = (over - 1.0) * 100.0
    return f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"


def _adjustments_cell(adjustments: Mapping[str, float]) -> str:
    if not adjustments:
        return "none"
    return "; ".join(
        f"{feature} {_signed_dollars(dollars)}"
        for feature, dollars in adjustments.items()
    )


def _valuation_fields(v: HomeValuation, valued_at: str) -> list[tuple[str, object]]:
    """The frontmatter fields to write back for one valued home, in note order.
    Empty when no price could be predicted (nothing computed to write)."""
    if v.predicted_price is None:
        return []
    fields: list[tuple[str, object]] = [
        ("predicted_price", v.predicted_price),
        ("predicted_low", v.predicted_low),
        ("predicted_high", v.predicted_high),
    ]
    if v.implied_over_list is not None:
        fields.append(("implied_over_list", v.implied_over_list))
    fields.extend([
        ("valuation_confidence", v.confidence),
        ("comps_used", v.comps_used),
        ("valued_at", valued_at),
    ])
    return fields


def _valuation_body(v: HomeValuation) -> str:
    """The ``## Valuation`` section content (below the heading): a summary line, the
    per-comp adjustment table, and a provenance footer. Auditable by design."""
    if v.predicted_price is None or v.predicted_low is None or v.predicted_high is None:
        return f"No valuation: {v.reason}."
    lines = [
        f"Predicted **{_dollars(v.predicted_price)}**, "
        f"90% band **{_dollars(v.predicted_low)}-{_dollars(v.predicted_high)}**, "
        f"over/under list **{_pct_over(v.implied_over_list)}**, "
        f"confidence **{v.confidence}** ({v.basis}), {v.comps_used} comps used. "
        f"{v.reason}."
    ]
    if v.breakdown:
        lines.extend([
            "",
            "| Comp | Sold | Sale price | Adjustments (subject - comp) | Adjusted | Weight |",
            "|---|---|---|---|---|---|",
        ])
        lines.extend(
            f"| {ca.address} | {ca.sale_date or '?'} | {_dollars(ca.sale_price)} "
            f"| {_adjustments_cell(ca.adjustments)} | {_dollars(ca.adjusted_price)} "
            f"| {ca.weight:.2f} |"
            for ca in v.breakdown
        )
    lines.extend([
        "",
        "_Schedule: [[Adjustments]]. Comps: `Projects/Home Search/Homes/data/comps.csv`. "
        "Generated by `vault-tool homes value`._",
    ])
    return "\n".join(lines)


def _plan_value(
    fp: Path,
    schedule: Sequence[Adjustment],
    ratios: OfferRatios,
    valued_at: str,
    now_year: int,
    comps_path: Path,
) -> _HomePlan:
    """Read one home, value it against its comps + the schedule, and fold the
    result (frontmatter scalars + a ``## Valuation`` body table) into new text."""
    text = fp.read_text(encoding="utf-8")
    rel = str(rel_path(fp))
    if not text.startswith("---"):
        return _HomePlan(
            fp, {"path": rel, "error": "no frontmatter block", "changed": False}, None, False
        )
    post = frontmatter.loads(text)
    list_price = _as_num(post.metadata.get("list_price"))
    slug = subject_slug(fp)
    comps = load_comps(slug, comps_path)
    v = value_home(post.metadata, comps, schedule, ratios, list_price, now_year)
    new_text = text
    for name, value in _valuation_fields(v, valued_at):
        new_text = patch_field(new_text, name, value)
    if v.predicted_price is not None:
        new_text = upsert_section(new_text, "## Valuation", _valuation_body(v))
    changed = new_text != text
    report: dict[str, object] = {
        "path": rel,
        "changed": changed,
        "subject": slug,
        "comps_used": v.comps_used,
        "basis": v.basis,
        "predicted_price": v.predicted_price,
        "predicted_low": v.predicted_low,
        "predicted_high": v.predicted_high,
        "implied_over_list": v.implied_over_list,
        "confidence": v.confidence,
        "reason": v.reason,
        "unvalued": v.predicted_price is None,
    }
    return _HomePlan(fp, report, new_text, changed)


def run_value(
    paths: list[str], write: bool, valued_at: str, now_year: int
) -> dict[str, object]:
    """Plan and (optionally) apply comp-based valuations across homes.

    Reads the offer-ratio prior from ``Criteria.md``, the adjustment schedule from
    ``Adjustments.md``, and each subject's comps from the comps store; writes back
    the predicted price, band, over/under-list, and an auditable ``## Valuation``
    table. Same all-or-nothing batch write as :func:`run_score`."""
    criteria_path = VAULT / _CRITERIA_REL
    if not criteria_path.exists():
        raise HomesError(f"criteria note not found: {_CRITERIA_REL}")
    _criteria, ratios = load_criteria(criteria_path)
    adjustments_path = VAULT / _ADJUSTMENTS_REL
    if not adjustments_path.exists():
        raise HomesError(f"adjustments note not found: {_ADJUSTMENTS_REL}")
    schedule = load_adjustments(adjustments_path)
    comps_path = VAULT / COMPS_REL

    if paths:
        files: list[Path] = []
        missing: list[str] = []
        for p in paths:
            fp = find_vault_file(p)
            if fp is None:
                missing.append(p)
            else:
                files.append(fp)
        if missing:
            raise HomesError(f"file(s) not found: {', '.join(missing)}")
    else:
        files = discover_home_files()

    plans = [
        _plan_value(fp, schedule, ratios, valued_at, now_year, comps_path)
        for fp in files
    ]
    errored = [pl for pl in plans if "error" in pl.report]
    do_write = write and not errored
    if do_write:
        for pl in plans:
            if pl.changed and pl.new_text is not None:
                pl.fp.write_text(pl.new_text, encoding="utf-8")

    valued = sum(
        1 for pl in plans if not pl.report.get("unvalued") and "error" not in pl.report
    )
    result: dict[str, object] = {
        "ok": not errored,
        "cmd": "homes value",
        "dryRun": not write,
        "written": do_write,
        "schedule_source": _ADJUSTMENTS_REL,
        "comps_source": COMPS_REL,
        "features": len(schedule),
        "summary": {
            "homes": len(plans),
            "valued": valued,
            "prior_fallback": sum(1 for pl in plans if pl.report.get("basis") == "prior"),
            "unvalued": sum(1 for pl in plans if pl.report.get("unvalued")),
            "changed": sum(1 for pl in plans if pl.changed),
            "errored": len(errored),
        },
        "homes": [pl.report for pl in plans],
    }
    if write and errored:
        result["aborted"] = "no files written: fix the errored homes above and retry"
    return result


def run_comps(args: _Args, fetched_at: str) -> dict[str, object]:
    """``homes comps fetch``: pull comps for one subject from RentCast into the
    store. A dry run (no ``--write``) previews the request without spending one of
    the free monthly requests; ``--write`` calls RentCast and appends deduped rows.
    """
    if args.comps_command != "fetch":
        raise HomesError(f"unknown comps subcommand: {args.comps_command}")
    if args.file is None:
        raise HomesError("comps fetch requires --file")
    fp = find_vault_file(args.file)
    if fp is None:
        raise HomesError(f"file not found: {args.file}")
    post = frontmatter.loads(fp.read_text(encoding="utf-8"))
    address = fm_str(post.metadata, "address")
    if not address:
        raise HomesError(f"{fp.name}: no 'address' in frontmatter to query RentCast")
    slug = subject_slug(fp)
    comps_path = VAULT / COMPS_REL
    existing = load_comps(slug, comps_path)

    base: dict[str, object] = {
        "ok": True,
        "cmd": "homes comps fetch",
        "subject": slug,
        "address": address,
        "count": args.count,
        "existing_comps": len(existing),
    }
    if not args.write:
        base["dryRun"] = True
        base["written"] = False
        base["note"] = (
            "dry run: no request spent. Re-run with --write to call RentCast "
            "(uses 1 of the free monthly requests)."
        )
        return base

    api_key = require_env("RENTCAST_API_KEY")
    try:
        fetched = fetch_comps(address, api_key, slug, args.count)
    except APIError as e:
        raise HomesError(f"RentCast request failed: {e}") from e
    added, skipped = append_comps(fetched, comps_path)
    base["dryRun"] = False
    base["written"] = added > 0
    base["fetched_at"] = fetched_at
    base["fetched"] = len(fetched)
    base["added"] = added
    base["skipped_duplicates"] = skipped
    base["total_comps"] = len(existing) + added
    return base


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vault-tool homes",
        description="Rubric scorer and comp-based valuation for the Homes tracker.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_score = sub.add_parser(
        "score", help="Compute weighted rubric scores for homes and write them back"
    )
    _ = p_score.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="home notes to score (default: every #home note in Projects/Home Search/Homes/entries/)",
    )
    _ = p_score.add_argument(
        "--write", action="store_true", help="apply changes (default: dry run)"
    )

    p_value = sub.add_parser(
        "value", help="Predict sale price from comps + the adjustment schedule"
    )
    _ = p_value.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="home notes to value (default: every #home note in Projects/Home Search/Homes/entries/)",
    )
    _ = p_value.add_argument(
        "--write", action="store_true", help="apply changes (default: dry run)"
    )

    p_comps = sub.add_parser("comps", help="Manage the comparable-sales store")
    comps_sub = p_comps.add_subparsers(dest="comps_command", required=True)
    p_fetch = comps_sub.add_parser(
        "fetch", help="Fetch comps for one home from RentCast (free tier)"
    )
    _ = p_fetch.add_argument("--file", required=True, help="the subject home note")
    _ = p_fetch.add_argument(
        "--count", type=int, default=15, help="comparables to request (default 15)"
    )
    _ = p_fetch.add_argument(
        "--write",
        action="store_true",
        help="spend a RentCast request and append comps (default: dry-run preview)",
    )
    return parser


def _dispatch(args: _Args, stamp: str, now_year: int) -> dict[str, object]:
    """Route a parsed invocation to its runner. argparse guarantees a known
    command; the final raise is a defensive fallback."""
    if args.command == "score":
        return run_score(args.paths, args.write, stamp)
    if args.command == "value":
        return run_value(args.paths, args.write, stamp, now_year)
    if args.command == "comps":
        return run_comps(args, stamp)
    raise HomesError(f"unknown command: {args.command}")


def main() -> None:
    args = parse_typed_args(_build_parser(), _Args)
    # Local calendar date/year for provenance (matches strava.py's convention).
    now = _dt.datetime.now(_dt.UTC).astimezone()
    try:
        result = _dispatch(args, now.date().isoformat(), now.year)
    except HomesError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

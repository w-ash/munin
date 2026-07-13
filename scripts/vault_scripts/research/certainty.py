"""Source-weighted certainty as additive log-odds, as pure functions.

The `verify` mode asks "are these claims true?" Its atom is the *source*, and
authority matters: a claim's certainty moves by a fixed, tier-based
log-likelihood increment (decibans) per supporting or refuting source. Updates
accumulate in log-odds, which is additive and order-independent, so evidence
composes by summation no matter what order it arrives in. Certainty maps to
calibrated bands; a ceiling gate blocks the top bands without a primary source.

This is a consistency convention across sources, not automatically a calibrated
probability; ``research calibrate`` checks it against the human labels in
``data/gold.csv`` when a topic has them.
Certainty is never stored; callers recompute it from the evidence rows on every
run, the same computed-never-stored contract as `confidence.py`.

Ported from munin's ``deep-research`` evidence engine (deciban accumulation,
tier/strength/domain factors, no-primary ceiling); written fresh here because
``confidence.py`` is linear-additive with no log/logit.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
import math
from urllib.parse import urlsplit

from vault_scripts.research.confidence import CELL_SEP

# Source vocabularies, exported so the store validators reject unknown values.
SOURCE_TIERS: frozenset[str] = frozenset({"primary", "community", "secondary", "weak"})
STRENGTHS: frozenset[str] = frozenset({"weak", "moderate", "strong"})
BEARINGS: frozenset[str] = frozenset({"supports", "refutes"})

# Base weight of evidence (decibans) for a *strong* item of each tier. A deciban
# is 10*log10 of the likelihood ratio; ~10 dB is a 10x update, and a deciban is
# roughly the smallest change in belief a person perceives (Good/Turing).
_TIER_DECIBANS: dict[str, float] = {
    "primary": 12.0,  # own authorship, peer-reviewed, official record
    "community": 8.0,  # a named human recommendation
    "secondary": 6.0,  # self-authored profile / practice-site copy
    "weak": 2.0,  # aggregator rating, third-party listicle, inference
}
_STRENGTH_MULT: dict[str, float] = {"weak": 1 / 3, "moderate": 2 / 3, "strong": 1.0}

# Same-source diminishing returns: the k-th item sharing a host contributes less,
# so one site can't stack certainty by restating itself.
_DOMAIN_FACTORS: tuple[float, ...] = (1.0, 0.5, 0.25)

_LN10 = math.log(10.0)

# Band thresholds (certainty %, minimum for each band, high to low); the ceiling
# sits just below "confident" so a claim without a primary source can reach
# "likely" but no higher.
_BAND_MIN: dict[str, float] = {
    "established": 90.0,
    "confident": 75.0,
    "likely": 55.0,
    "tentative": 35.0,
    "speculative": 15.0,
}


@dataclass(frozen=True)
class CertaintyParams:
    """Tunable certainty model parameters; defaults are munin's convention."""

    prior: float = 0.5
    ceiling: float = 74.0
    ceiling_tier: str = "primary"


@dataclass(frozen=True)
class Evidence:
    """One sourced observation bearing on a claim (or a rank grid cell).

    ``claim_id`` is the claim (verify) or the ``<candidate>--<criterion>`` cell
    (rank) the row scores against; ``evidence_id`` is preserved so the citation
    pass can address rows individually.
    """

    evidence_id: str
    claim_id: str
    source_url: str
    source_tier: str
    strength: str
    bearing: str
    quote: str = ""


@dataclass(frozen=True)
class ScoreDriver:
    """One source's signed contribution to a claim's certainty, in decibans."""

    source_url: str
    source_tier: str
    bearing: str
    decibans: float


@dataclass(frozen=True)
class ClaimVerdict:
    """Scored certainty for one claim. ``claim`` is filled by the caller from
    the claims table (this engine sees only evidence rows, mirroring how
    ``score_map`` names categories from the taxonomy)."""

    claim_id: str
    certainty: float
    band: str
    net_decibans: float
    n_sources: int
    capped: bool
    drivers: list[ScoreDriver] = field(default_factory=list)
    claim: str = ""


def _domain(url: str) -> str:
    parts = urlsplit(url)
    # A scheme-less URL ("example.com/x") parses with an empty netloc and the
    # host in the path; fall back to the first path segment so distinct hosts
    # don't collapse into one "" domain and trip same-host diminishing returns.
    host = parts.netloc or parts.path.lstrip("/").split("/", 1)[0]
    return host.lower().removeprefix("www.")


def woe_decibans(item: Evidence) -> float:
    """Signed weight of evidence for one item, in decibans."""
    base = _TIER_DECIBANS[item.source_tier]
    mult = _STRENGTH_MULT[item.strength]
    sign = 1.0 if item.bearing == "supports" else -1.0
    return sign * base * mult


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def band(certainty: float) -> str:
    """Map a certainty percentage to its band label."""
    for label, low in _BAND_MIN.items():
        if certainty >= low:
            return label
    return "refuted"


def _dedup(items: list[Evidence]) -> list[Evidence]:
    """Drop exact duplicates (same source, bearing, quote) so a re-seeded row
    does not double-count."""
    seen: set[tuple[str, str, str]] = set()
    out: list[Evidence] = []
    for it in items:
        key = (it.source_url, it.bearing, it.quote)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def score_claim(
    items: list[Evidence], claim_id: str, *, params: CertaintyParams | None = None
) -> ClaimVerdict:
    """Accumulate one claim's evidence into a calibrated certainty. Pure and
    order-independent: log-odds is additive, so shuffling ``items`` cannot
    change the result."""
    params = params or CertaintyParams()
    uniq = _dedup(items)
    by_domain: dict[str, list[Evidence]] = {}
    for it in uniq:
        by_domain.setdefault(_domain(it.source_url), []).append(it)

    net = 0.0
    drivers: list[ScoreDriver] = []
    for group in by_domain.values():
        ranked = sorted(group, key=lambda x: abs(woe_decibans(x)), reverse=True)
        for i, it in enumerate(ranked):
            factor = _DOMAIN_FACTORS[min(i, len(_DOMAIN_FACTORS) - 1)]
            db = woe_decibans(it) * factor
            net += db
            drivers.append(
                ScoreDriver(
                    source_url=it.source_url,
                    source_tier=it.source_tier,
                    bearing=it.bearing,
                    decibans=round(db, 2),
                )
            )

    logodds = _logit(params.prior) + net / 10.0 * _LN10
    certainty = _sigmoid(logodds) * 100.0

    has_primary_support = any(
        it.bearing == "supports" and it.source_tier == params.ceiling_tier
        for it in uniq
    )
    capped = False
    if not has_primary_support and certainty > params.ceiling:
        certainty = params.ceiling
        capped = True

    drivers.sort(key=lambda d: abs(d.decibans), reverse=True)
    certainty = round(certainty, 1)
    return ClaimVerdict(
        claim_id=claim_id,
        certainty=certainty,
        band=band(certainty),
        net_decibans=round(net, 2),
        n_sources=len({it.source_url for it in uniq}),
        capped=capped,
        drivers=drivers,
    )


def score_items(
    items: Iterable[Evidence],
    claim_ids: Iterable[str],
    *,
    params: CertaintyParams | None = None,
) -> list[ClaimVerdict]:
    """Score every claim id from its evidence rows, ranked by certainty.

    ``claim_ids`` is the registered claim list, so a claim with no evidence
    still scores (at the prior) instead of vanishing. Evidence whose
    ``claim_id`` is not registered is ignored (``VOID`` rows, drift)."""
    by_claim: dict[str, list[Evidence]] = {cid: [] for cid in claim_ids}
    for it in items:
        if it.claim_id in by_claim:
            by_claim[it.claim_id].append(it)
    verdicts = [
        score_claim(group, cid, params=params) for cid, group in by_claim.items()
    ]
    verdicts.sort(key=lambda v: v.certainty, reverse=True)
    return verdicts


# How each citation status feeds back into scoring: a fabricated-looking quote
# is inadmissible in either bearing; merely-unverified sourcing loses one
# strength level so it still contributes but cannot carry a verdict.
_DOWNGRADE: dict[str, str] = {"strong": "moderate", "moderate": "weak", "weak": "weak"}


def apply_citations(
    items: list[Evidence], verdicts: dict[str, str]
) -> tuple[list[Evidence], dict[str, int]]:
    """Fold mechanical citation checks (``data/citations.csv``, keyed by
    ``evidence_id``) into the evidence before scoring. ``verified`` passes
    through; ``quote_missing`` is excluded; everything else (dead, unfetchable,
    no_quote, or unchecked) is downgraded one strength level."""
    from vault_scripts.research.verify import QUOTE_MISSING, VERIFIED  # noqa: PLC0415

    kept: list[Evidence] = []
    stats = {"verified": 0, "excluded_quote_missing": 0, "downgraded": 0}
    for it in items:
        status = verdicts.get(it.evidence_id)
        if status == VERIFIED:
            stats["verified"] += 1
            kept.append(it)
        elif status == QUOTE_MISSING:
            stats["excluded_quote_missing"] += 1
        else:
            stats["downgraded"] += 1
            kept.append(replace(it, strength=_DOWNGRADE[it.strength]))
    return kept, stats


# --- Ranking (rubric rollup; each grid cell is an ordinary scored claim) ---

# The rank criterion tiers, exported so the store validator rejects unknown
# values; blocker/must are the "load-bearing" set used for weakest-link and
# evidence-gap reporting.
CRITERION_TIERS: frozenset[str] = frozenset({"blocker", "must", "should", "nice"})
_LOAD_BEARING: frozenset[str] = frozenset({"blocker", "must"})

# A load-bearing (blocker/must) cell resting on fewer sources than this is an
# evidence gap: the natural target for a re-research round.
_GAP_MIN_SOURCES = 2


@dataclass(frozen=True)
class Candidate:
    """One option being ranked. ``id`` is the slug used in cell ids
    (``<candidate>--<criterion>``); ``name`` is the display name."""

    id: str
    name: str = ""


@dataclass(frozen=True)
class Criterion:
    """One rubric criterion. ``weight`` sets its share of the fit score;
    ``tier`` sets its gating role (a failing ``blocker`` caps the candidate;
    ``blocker``/``must`` are load-bearing for weakest-link reporting)."""

    id: str
    weight: float = 1.0
    tier: str = "should"


@dataclass(frozen=True)
class CriterionScore:
    """One rubric cell's scored certainty inside a candidate verdict."""

    criterion_id: str
    tier: str
    weight: float
    certainty: float
    band: str
    n_sources: int
    capped: bool


@dataclass(frozen=True)
class CandidateVerdict:
    """Ranked fit verdict for one candidate."""

    candidate_id: str
    candidate: str
    score: float
    blocked: bool
    blocked_by: list[str]
    least_resolved: str
    evidence_gaps: list[str]
    criteria: list[CriterionScore]


def rank_candidates(
    items: list[Evidence],
    candidates: list[Candidate],
    criteria: list[Criterion],
    *,
    params: CertaintyParams | None = None,
    blocker_threshold: float = 50.0,
) -> list[CandidateVerdict]:
    """Roll per-cell claim certainties (``<candidate>--<criterion>``) up into
    per-candidate fit scores. Deterministic: every number comes from the same
    weight-of-evidence engine as ``score_claim``.

    - fit = weight-normalized mean of criterion certainties (0-100).
    - A ``blocker`` below ``blocker_threshold`` marks the candidate blocked and
      caps its fit at that criterion's certainty.
    - A cell with no evidence sits at the prior (unknown, not failing). Thin
      load-bearing cells surface as ``evidence_gaps``; ``least_resolved`` names
      the load-bearing criterion nearest 50, the natural re-research target.
    - A blocked candidate never outranks a clean one regardless of fit.
    """
    total_weight = sum(c.weight for c in criteria)
    if total_weight <= 0:
        raise ValueError("rank rubric has no positive criterion weight")
    by_cell: dict[str, list[Evidence]] = {}
    for it in items:
        by_cell.setdefault(it.claim_id, []).append(it)

    verdicts: list[CandidateVerdict] = []
    for cand in candidates:
        scores: list[CriterionScore] = []
        for crit in criteria:
            cell_id = f"{cand.id}{CELL_SEP}{crit.id}"
            cv = score_claim(by_cell.get(cell_id, []), cell_id, params=params)
            scores.append(
                CriterionScore(
                    criterion_id=crit.id,
                    tier=crit.tier,
                    weight=crit.weight,
                    certainty=cv.certainty,
                    band=cv.band,
                    n_sources=cv.n_sources,
                    capped=cv.capped,
                )
            )

        fit = sum(s.certainty * s.weight for s in scores) / total_weight
        failing = [
            s for s in scores if s.tier == "blocker" and s.certainty < blocker_threshold
        ]
        if failing:
            fit = min(fit, *(s.certainty for s in failing))
        load_bearing = [s for s in scores if s.tier in _LOAD_BEARING]
        least_resolved = (
            min(load_bearing, key=lambda s: abs(s.certainty - 50.0)).criterion_id
            if load_bearing
            else ""
        )
        verdicts.append(
            CandidateVerdict(
                candidate_id=cand.id,
                candidate=cand.name or cand.id,
                score=round(fit, 1),
                blocked=bool(failing),
                blocked_by=[s.criterion_id for s in failing],
                least_resolved=least_resolved,
                evidence_gaps=[
                    s.criterion_id
                    for s in load_bearing
                    if s.n_sources < _GAP_MIN_SOURCES
                ],
                criteria=scores,
            )
        )
    # Unblocked first, then by fit: a blocked candidate never outranks a clean one.
    verdicts.sort(key=lambda v: (not v.blocked, v.score), reverse=True)
    return verdicts

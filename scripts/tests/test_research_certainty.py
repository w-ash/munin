"""The decibans certainty engine: additive log-odds, ceiling, banding."""

import pytest

from vault_scripts.research import certainty
from vault_scripts.research.certainty import (
    Candidate,
    CertaintyParams,
    Criterion,
    Evidence,
    rank_candidates,
    score_claim,
    score_items,
)
from vault_scripts.research.verify import QUOTE_MISSING, UNFETCHABLE, VERIFIED


def ev(
    eid: str,
    claim: str,
    url: str,
    tier: str,
    strength: str = "strong",
    bearing: str = "supports",
) -> Evidence:
    return Evidence(eid, claim, url, tier, strength, bearing, quote="q")


def test_scheme_less_urls_stay_distinct_domains() -> None:
    # Bare "host/path" URLs (no https://) must not all collapse into one empty
    # domain and trigger same-host diminishing returns on unrelated sources.
    items = [
        ev("E1", "C", "example.com/a", "primary"),
        ev("E2", "C", "other.org/b", "primary"),
    ]
    v = score_claim(items, "C")
    # Two independent primaries at full weight: 12 + 12 = 24 dB, not 12 + 6.
    assert v.net_decibans == 24.0


def test_supporting_primary_reads_high() -> None:
    v = score_claim([ev("E1", "C", "https://a.com/1", "primary")], "C")
    assert v.net_decibans == 12.0
    assert v.n_sources == 1
    assert not v.capped
    assert v.band in {"likely", "confident", "established"}


def test_log_odds_is_order_independent() -> None:
    items = [
        ev("E1", "C", "https://a.com/1", "primary"),
        ev("E2", "C", "https://b.com/2", "secondary", "moderate"),
        ev("E3", "C", "https://c.com/3", "weak", "weak", "refutes"),
    ]
    forward = score_claim(items, "C")
    backward = score_claim(list(reversed(items)), "C")
    assert forward.certainty == backward.certainty
    assert forward.net_decibans == backward.net_decibans


def test_same_domain_diminishes() -> None:
    """The 2nd and 3rd item from a host contribute half then a quarter."""
    items = [ev(f"E{i}", "C", f"https://h.com/{i}", "primary") for i in range(3)]
    v = score_claim(items, "C")
    assert v.net_decibans == 12.0 + 6.0 + 3.0  # 21.0
    assert v.n_sources == 3


def test_refutation_subtracts() -> None:
    supports = score_claim([ev("E1", "C", "https://a.com/1", "primary")], "C")
    with_refute = score_claim(
        [
            ev("E1", "C", "https://a.com/1", "primary"),
            ev("E2", "C", "https://b.com/2", "primary", bearing="refutes"),
        ],
        "C",
    )
    assert with_refute.net_decibans == 0.0
    assert with_refute.certainty < supports.certainty


def test_no_primary_support_hits_ceiling() -> None:
    """Stacked non-primary support can reach 'likely' but is capped below
    'confident' without a supporting primary source."""
    items = [
        ev("E1", "C", "https://a.com/1", "secondary"),
        ev("E2", "C", "https://b.com/2", "community"),
        ev("E3", "C", "https://c.com/3", "secondary"),
    ]
    v = score_claim(items, "C")
    assert v.capped
    assert v.certainty == 74.0
    assert v.band == "likely"


def test_primary_refutation_does_not_lift_ceiling() -> None:
    """A primary source that *refutes* is not supporting primary evidence, so
    the no-primary ceiling still applies."""
    items = [
        ev("E1", "C", "https://a.com/1", "secondary"),
        ev("E2", "C", "https://b.com/2", "community"),
        ev("E3", "C", "https://c.com/3", "secondary"),
        ev("E4", "C", "https://d.com/4", "primary", bearing="refutes"),
    ]
    v = score_claim(items, "C")
    # Net is positive (8 dB) so pre-cap certainty clears the ceiling, but no
    # *supporting* primary source exists, so the ceiling still clamps it.
    assert v.capped
    assert v.certainty == 74.0


def test_empty_claim_sits_at_prior() -> None:
    v = score_claim([], "C", params=CertaintyParams(prior=0.5))
    assert v.certainty == 50.0
    assert v.n_sources == 0
    assert v.net_decibans == 0.0


def test_bands_partition_the_range() -> None:
    assert certainty.band(95.0) == "established"
    assert certainty.band(80.0) == "confident"
    assert certainty.band(60.0) == "likely"
    assert certainty.band(40.0) == "tentative"
    assert certainty.band(20.0) == "speculative"
    assert certainty.band(5.0) == "refuted"


def test_score_items_ranks_and_covers_empty_claims() -> None:
    items = [
        ev("E1", "HIGH", "https://a.com/1", "primary"),
        ev("E2", "LOW", "https://b.com/2", "weak", "weak", "refutes"),
    ]
    verdicts = score_items(items, ["HIGH", "LOW", "UNSEEN"])
    ids = [v.claim_id for v in verdicts]
    assert ids[0] == "HIGH"  # ranked by certainty, descending
    assert "UNSEEN" in ids  # a registered claim with no evidence still scores
    unseen = next(v for v in verdicts if v.claim_id == "UNSEEN")
    assert unseen.certainty == 50.0


def test_apply_citations_excludes_and_downgrades() -> None:
    items = [
        ev("E1", "C", "https://a.com/1", "primary", "strong"),
        ev("E2", "C", "https://b.com/2", "primary", "strong"),
        ev("E3", "C", "https://c.com/3", "primary", "strong"),
    ]
    verdicts = {"E1": VERIFIED, "E2": QUOTE_MISSING, "E3": UNFETCHABLE}
    kept, stats = certainty.apply_citations(items, verdicts)
    assert stats == {"verified": 1, "excluded_quote_missing": 1, "downgraded": 1}
    kept_by_id = {it.evidence_id: it for it in kept}
    assert "E2" not in kept_by_id  # excluded
    assert kept_by_id["E1"].strength == "strong"  # verified passes through
    assert kept_by_id["E3"].strength == "moderate"  # unfetchable downgraded one level


# --- rank rollup ---


def cell(
    cand: str,
    crit: str,
    *,
    url: str = "https://a.org/1",
    tier: str = "primary",
    bearing: str = "supports",
    strength: str = "strong",
) -> Evidence:
    return Evidence(
        f"{cand}-{crit}", f"{cand}--{crit}", url, tier, strength, bearing, "q"
    )


DEFAULT_CRITERIA = [
    Criterion(id="fit", weight=2.0, tier="must"),
    Criterion(id="price", weight=1.0, tier="should"),
]


def test_rank_no_evidence_sits_at_prior() -> None:
    verdicts = rank_candidates([], [Candidate("a"), Candidate("b")], DEFAULT_CRITERIA)
    assert [v.score for v in verdicts] == [50.0, 50.0]
    assert all(
        s.certainty == 50.0 and s.n_sources == 0 for v in verdicts for s in v.criteria
    )


def test_rank_weighted_rollup_orders_candidates() -> None:
    items = [
        cell("a", "fit"),
        cell("a", "price", url="https://b.org/2"),
        cell("b", "fit", bearing="refutes"),
    ]
    verdicts = rank_candidates(
        items, [Candidate("a"), Candidate("b")], DEFAULT_CRITERIA
    )
    assert [v.candidate_id for v in verdicts] == ["a", "b"]
    a, b = verdicts
    assert a.score > 50.0 > b.score
    fit_c = next(s.certainty for s in a.criteria if s.criterion_id == "fit")
    price_c = next(s.certainty for s in a.criteria if s.criterion_id == "price")
    assert a.score == round((fit_c * 2.0 + price_c * 1.0) / 3.0, 1)


def test_rank_blocker_gates_and_sorts_last() -> None:
    criteria = [
        Criterion(id="deal-breaker", weight=1.0, tier="blocker"),
        Criterion(id="nice", weight=10.0, tier="nice"),
    ]
    items = [
        cell("a", "deal-breaker", bearing="refutes"),  # fails the blocker
        cell("a", "nice"),  # aces the heavy nice-to-have
        cell("b", "deal-breaker", tier="secondary", strength="weak"),  # clean, mediocre
    ]
    verdicts = rank_candidates(items, [Candidate("a"), Candidate("b")], criteria)
    by_id = {v.candidate_id: v for v in verdicts}
    assert by_id["a"].blocked
    assert by_id["a"].blocked_by == ["deal-breaker"]
    blocker_c = next(
        s.certainty for s in by_id["a"].criteria if s.criterion_id == "deal-breaker"
    )
    assert by_id["a"].score <= blocker_c  # capped at the failing blocker
    assert not by_id["b"].blocked
    assert [v.candidate_id for v in verdicts] == ["b", "a"]  # clean outranks blocked


def test_rank_least_resolved_and_evidence_gaps() -> None:
    criteria = [
        Criterion(id="strong-evidence", weight=1.0, tier="must"),
        Criterion(id="thin", weight=1.0, tier="must"),
        Criterion(id="ignored", weight=1.0, tier="nice"),
    ]
    items = [
        cell("a", "strong-evidence"),
        cell("a", "strong-evidence", url="https://b.org/2"),
        cell("a", "thin", tier="weak", strength="weak"),
    ]
    (v,) = rank_candidates(items, [Candidate("a")], criteria)
    assert v.least_resolved == "thin"  # closest to the prior among load-bearing
    assert v.evidence_gaps == ["thin"]  # nice-tier "ignored" is not load-bearing


def test_rank_zero_weight_is_error() -> None:
    with pytest.raises(ValueError, match="positive criterion weight"):
        rank_candidates([], [Candidate("a")], [Criterion(id="x", weight=0.0)])

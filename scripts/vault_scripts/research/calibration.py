"""Scorer calibration against a human-labeled gold set, as pure functions.

The harness's per-item scores (map's category confidence, verify's claim
certainty, rank's per-cell certainty) are consistency conventions across
sources until checked against reality. ``research calibrate`` compares each
scored probability with a human ``true``/``false`` label from ``data/gold.csv``
and reports a reliability table plus two summary numbers:

- **ECE** (expected calibration error): the bin-weighted mean gap between the
  average predicted probability and the observed hit rate. Zero means the
  scorer's numbers can be read as frequencies.
- **Brier score**: mean squared error of the probabilities against the labels;
  rewards both calibration and discrimination.

Assumption-free by design: fixed equal-width bins, no fitting, no smoothing.
Empty bins stay in the report with ``n=0`` so sparse gold sets read as sparse
rather than silently clean. Nothing is stored; the CLI recomputes on every run.

The split-conformal helpers turn the same gold data into finite-sample
coverage statements: ``binary_scores`` + ``conformal_quantile`` give the
probability modes a threshold with guaranteed (1-alpha) coverage over
exchangeable items, and ``standardized_log_residuals`` +
``conformal_log_interval`` conformalize an analytic lognormal estimate from
per-factor realized values. Data-gated: below ``MIN_CALIBRATION_N`` labels the
caller reports "ineligible" rather than trusting a quantile that barely
exists. Coverage assumes exchangeability (no test here; correlated or
drifting items degrade it silently), so small sets widen conservatively via
the finite-sample rank rather than being trusted at nominal coverage.
"""

from collections.abc import Sequence
from dataclasses import dataclass
import math

from vault_scripts.research.magnitude import sig_figs

# Fixed equal-width reliability bins: [0.0,0.1) ... [0.9,1.0] (last bin closed).
N_BINS = 10

# Below this many gold labels the numbers are directional at best; it is also
# the eligibility gate for the conformal layer (a smaller calibration set has
# no meaningful finite-sample quantile at the 90% level).
MIN_CALIBRATION_N = 20

# Conformal miscoverage level: 90% coverage, matching estimate's default ci.
ALPHA = 0.10


@dataclass(frozen=True)
class ReliabilityBin:
    """One probability bin: how often "true" actually occurred there."""

    lower: float
    upper: float
    n: int
    mean_probability: float | None  # None when the bin is empty
    hit_rate: float | None


@dataclass(frozen=True)
class CalibrationReport:
    """A reliability check over (probability, label) pairs."""

    n: int
    bins: tuple[ReliabilityBin, ...]
    ece: float
    brier: float


def reliability(
    pairs: Sequence[tuple[float, bool]], *, n_bins: int = N_BINS
) -> CalibrationReport:
    """Bin the (probability, label) pairs and compute ECE and Brier."""
    if not pairs:
        raise ValueError("reliability needs at least one (probability, label) pair")
    for p, _ in pairs:
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"probability out of range [0, 1]: {p}")

    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for p, label in pairs:
        buckets[min(int(p * n_bins), n_bins - 1)].append((p, label))

    n = len(pairs)
    bins: list[ReliabilityBin] = []
    ece = 0.0
    for i, bucket in enumerate(buckets):
        lower, upper = round(i / n_bins, 4), round((i + 1) / n_bins, 4)
        if not bucket:
            bins.append(ReliabilityBin(lower, upper, 0, None, None))
            continue
        mean_p = sum(p for p, _ in bucket) / len(bucket)
        hit_rate = sum(1 for _, label in bucket if label) / len(bucket)
        ece += len(bucket) / n * abs(hit_rate - mean_p)
        bins.append(
            ReliabilityBin(
                lower, upper, len(bucket), round(mean_p, 4), round(hit_rate, 4)
            )
        )

    brier = sum((p - (1.0 if label else 0.0)) ** 2 for p, label in pairs) / n
    return CalibrationReport(
        n=n, bins=tuple(bins), ece=round(ece, 4), brier=round(brier, 4)
    )


def binary_scores(pairs: Sequence[tuple[float, bool]]) -> list[float]:
    """Split-conformal nonconformity for binary labels: how wrong was p."""
    return [(1.0 - p) if label else p for p, label in pairs]


def conformal_quantile(scores: Sequence[float], alpha: float) -> float:
    """The finite-sample (1-alpha) split-conformal quantile of the scores.

    The ceil((n+1)(1-alpha))-th smallest score: inherently conservative for
    small n (the rank rounds up, never down). Raises when the rank does not
    exist; callers gate on ``MIN_CALIBRATION_N`` before getting here.
    """
    n = len(scores)
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1): {alpha}")
    rank = math.ceil((n + 1) * (1.0 - alpha))
    if rank > n:
        raise ValueError(f"calibration set too small for alpha={alpha}: n={n}")
    return sorted(scores)[rank - 1]


def standardized_log_residuals(
    triples: Sequence[tuple[float, float, float]],
) -> list[float]:
    """Nonconformity for lognormal factors: |ln(actual) - mu| / sigma.

    Each triple is a labeled factor's (mu, sigma, actual). A sigma of zero
    makes no uncertainty claim to check, so callers exclude point factors
    before getting here; a non-positive actual has no logarithm.
    """
    scores: list[float] = []
    for mu, sigma, actual in triples:
        if sigma <= 0.0:
            raise ValueError(f"sigma must be positive: {sigma}")
        if actual <= 0.0:
            raise ValueError(f"actual must be positive: {actual}")
        scores.append(abs(math.log(actual) - mu) / sigma)
    return scores


def conformal_log_interval(
    median: float, sigma_total: float, q_hat: float
) -> tuple[float, float]:
    """Conformalized interval for an analytic lognormal estimate.

    The analytic total is lognormal(mu_total, sigma_total), so scaling the
    log-space half-width by the conformal quantile of the standardized
    residuals gives ``median * exp(-+ q_hat * sigma_total)``. Only valid on
    the analytic path; a mixed additive total is not lognormal and a single
    log-space quantile would be dishonest there.
    """
    spread = math.exp(q_hat * sigma_total)
    return sig_figs(median / spread), sig_figs(median * spread)

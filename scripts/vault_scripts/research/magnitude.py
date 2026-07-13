"""Quantitative sizing as propagated uncertainty, as pure functions.

The `estimate` mode asks "how big / how much, now?" Its answer is a *magnitude
with a range*, not a point: a target quantity decomposed into uncertain
sub-factors (a Fermi decomposition), each factor a lognormal read from a low/
high 90% interval. Two propagation paths, chosen by the *structure* of the
decomposition, mirroring how Squiggle picks symbolic-vs-sampling:

- **Pure product / quotient** (every factor combines by ``mul`` or ``div``):
  the product of independent lognormals is lognormal in closed form, so we
  propagate analytically. Exact, deterministic, no sampling noise.
- **Sums or mixed structure** (any ``add`` / ``sub`` factor): a sum of
  lognormals has no closed form, so we fall back to seeded Monte Carlo. The
  fixed seed keeps the result reproducible (and pinned-envelope-testable).

Interval arithmetic is deliberately not offered: multiplying the lows and the
highs assumes worst-case correlation and compounds into a uselessly wide band.

Factors combine left-to-right the way arithmetic reads: ``mul``/``div`` extend
the current product term, ``add``/``sub`` start a new signed term, and the
target is the sum of the terms (``a*b + c*d`` is two terms). Written fresh (no
munin source; the log-space math is standard). Nothing is stored; the CLI
recomputes it every run.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
import math
import random
from statistics import NormalDist

OPS: frozenset[str] = frozenset({"mul", "div", "add", "sub"})
DISTRIBUTIONS: frozenset[str] = frozenset({"lognormal"})

ANALYTIC = "analytic-lognormal"
MONTE_CARLO = "monte-carlo"

# Input low/high are read as a 90% interval (5th/95th percentiles): the finder
# gives a plausible range, not a hard min/max.
_INPUT_CI = 90.0
_STD = NormalDist()


@dataclass(frozen=True)
class Factor:
    """One sub-factor of the decomposition. ``low``/``high`` bound a 90%
    interval; ``mid`` is the median (geometric mean of low/high when blank).
    ``op`` sets how it enters the formula (``mul``/``div`` within a product
    term, ``add``/``sub`` starting a new term)."""

    factor_id: str
    name: str
    op: str
    low: float
    high: float
    mid: float = 0.0
    distribution: str = "lognormal"


@dataclass(frozen=True)
class FactorStat:
    """A factor's log-space parameters and its share of the total log-variance
    (the uncertainty-contribution ranking; the largest is the swing driver)."""

    factor_id: str
    name: str
    op: str
    mu: float
    sigma: float
    variance_share: float


@dataclass(frozen=True)
class EstimateResult:
    """A sized magnitude with its interval and the dominant uncertainty."""

    method: str
    median: float
    low: float  # lower bound at the reported ci
    high: float  # upper bound at the reported ci
    ci: float
    sigma_total: float  # total log-space spread; the interval and any conformal reuse it
    dominant_factor: str
    factors: list[FactorStat] = field(default_factory=list)


def _z(ci: float) -> float:
    """The standard-normal quantile for a two-sided ``ci``% interval."""
    return _STD.inv_cdf((1.0 + ci / 100.0) / 2.0)


def _mu_sigma(f: Factor) -> tuple[float, float]:
    """Log-space median and spread from the factor's 90% low/high interval."""
    if f.low <= 0 or f.high <= 0:
        raise ValueError(f"factor {f.factor_id!r}: low/high must be positive")
    ln_lo, ln_hi = math.log(f.low), math.log(f.high)
    mu = math.log(f.mid) if f.mid > 0 else (ln_lo + ln_hi) / 2.0
    sigma = (ln_hi - ln_lo) / (2.0 * _z(_INPUT_CI))
    return mu, max(sigma, 0.0)


def _terms(factors: list[Factor]) -> list[tuple[float, list[Factor]]]:
    """Split factors into signed additive terms. ``mul``/``div`` extend the
    current term's product; ``add``/``sub`` open a new term (``sub`` negative)."""
    terms: list[tuple[float, list[Factor]]] = []
    for f in factors:
        if not terms or f.op in {"add", "sub"}:
            terms.append((-1.0 if f.op == "sub" else 1.0, [f]))
        else:
            terms[-1][1].append(f)
    return terms


def _is_pure_product(factors: list[Factor]) -> bool:
    """A single product term: every factor combines by ``mul``/``div``.

    The first factor's op counts too: a leading ``add``/``sub`` opens a signed
    term, which the analytic closed form cannot represent (it only negates
    ``div``), so such a decomposition must take the Monte Carlo path where
    ``_terms`` carries the sign."""
    return all(f.op in {"mul", "div"} for f in factors)


def sig_figs(x: float, digits: int = 4) -> float:
    """Round to ``digits`` significant figures; magnitudes span many orders."""
    if x == 0 or not math.isfinite(x):
        return x
    exp = math.floor(math.log10(abs(x)))
    return round(x, -(exp - (digits - 1)))


def _factor_stats(
    factors: list[Factor], params: list[tuple[float, float]]
) -> tuple[list[FactorStat], str]:
    total_var = sum(sigma * sigma for _, sigma in params)
    stats = [
        FactorStat(
            factor_id=f.factor_id,
            name=f.name or f.factor_id,
            op=f.op,
            mu=round(mu, 4),
            sigma=round(sigma, 4),
            variance_share=round((sigma * sigma / total_var) if total_var else 0.0, 4),
        )
        for f, (mu, sigma) in zip(factors, params, strict=True)
    ]
    dominant = max(stats, key=lambda s: s.variance_share).factor_id if stats else ""
    return stats, dominant


def propagate_lognormal(factors: list[Factor], *, ci: float) -> EstimateResult:
    """Closed-form propagation for a pure product/quotient of lognormals: log
    means add (subtracting for ``div``), log variances add. Deterministic."""
    params = [_mu_sigma(f) for f in factors]
    mu_total = sum(
        (-mu if f.op == "div" else mu)
        for f, (mu, _) in zip(factors, params, strict=True)
    )
    var_total = sum(sigma * sigma for _, sigma in params)
    sigma_total = math.sqrt(var_total)
    z = _z(ci)
    stats, dominant = _factor_stats(factors, params)
    return EstimateResult(
        method=ANALYTIC,
        median=sig_figs(math.exp(mu_total)),
        low=sig_figs(math.exp(mu_total - z * sigma_total)),
        high=sig_figs(math.exp(mu_total + z * sigma_total)),
        ci=ci,
        sigma_total=sigma_total,
        dominant_factor=dominant,
        factors=stats,
    )


def _percentile(sorted_draws: list[float], p: float) -> float:
    """Linear-interpolated percentile of a pre-sorted sample."""
    if not sorted_draws:
        return 0.0
    if len(sorted_draws) == 1:
        return sorted_draws[0]
    rank = p / 100.0 * (len(sorted_draws) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_draws[lo]
    return sorted_draws[lo] + (sorted_draws[hi] - sorted_draws[lo]) * (rank - lo)


def propagate_montecarlo(
    factors: list[Factor], *, ci: float, samples: int, seed: int
) -> EstimateResult:
    """Sampling propagation for sums / mixed structure. Seeded, so the result
    is reproducible across runs; each factor is drawn lognormal and the terms
    are summed per draw."""
    params = [_mu_sigma(f) for f in factors]
    terms = _terms(factors)
    mu_sigma = {f.factor_id: ms for f, ms in zip(factors, params, strict=True)}
    rng = random.Random(seed)  # noqa: S311 - a reproducible estimate, not cryptography

    draws: list[float] = []
    for _ in range(samples):
        drawn = {
            fid: rng.lognormvariate(mu, sigma) for fid, (mu, sigma) in mu_sigma.items()
        }
        total = 0.0
        for sign, term in terms:
            prod = 1.0
            for f in term:
                if f.op == "div":
                    prod /= drawn[f.factor_id]
                else:
                    prod *= drawn[f.factor_id]
            total += sign * prod
        draws.append(total)
    draws.sort()

    tail = (100.0 - ci) / 2.0
    stats, dominant = _factor_stats(factors, params)
    # Reported for parity with the analytic path; the summed distribution is not
    # lognormal, so the interval comes from the sampled percentiles, not this.
    sigma_total = math.sqrt(sum(sigma * sigma for _, sigma in params))
    return EstimateResult(
        method=MONTE_CARLO,
        median=sig_figs(_percentile(draws, 50.0)),
        low=sig_figs(_percentile(draws, tail)),
        high=sig_figs(_percentile(draws, 100.0 - tail)),
        ci=ci,
        sigma_total=sigma_total,
        dominant_factor=dominant,
        factors=stats,
    )


def estimate(
    factors: Iterable[Factor],
    *,
    ci: float = 90.0,
    mc_samples: int = 10000,
    mc_seed: int = 1729,
) -> EstimateResult:
    """Size the target, choosing the propagation path by structure: a pure
    product/quotient goes through the exact lognormal closed form; anything with
    an ``add``/``sub`` term falls back to seeded Monte Carlo."""
    fs = list(factors)
    if not fs:
        raise ValueError("estimate needs at least one factor")
    if _is_pure_product(fs):
        return propagate_lognormal(fs, ci=ci)
    return propagate_montecarlo(fs, ci=ci, samples=mc_samples, seed=mc_seed)

"""The magnitude engine: lognormal propagation, structural dispatch, Monte Carlo."""

import math

from vault_scripts.research import magnitude
from vault_scripts.research.magnitude import Factor


def _f(fid: str, low: float, high: float, op: str = "mul", mid: float = 0.0) -> Factor:
    return Factor(fid, fid, op, low=low, high=high, mid=mid)


def test_analytic_product_matches_hand_computation() -> None:
    # 1000 (fixed) x [0.05, 0.20] median 0.1 -> median 100, and a factor of 4
    # spread over the 90% interval maps to +/- one z90 in log space.
    factors = [_f("pop", 1000, 1000), _f("rate", 0.05, 0.20)]
    r = magnitude.estimate(factors)
    assert r.method == magnitude.ANALYTIC
    assert r.median == 100.0
    z = magnitude._z(90.0)  # exercising the documented interval math
    sigma = math.log(0.20 / 0.05) / (2 * z)
    assert r.low == magnitude.sig_figs(100 * math.exp(-z * sigma))
    assert r.high == magnitude.sig_figs(100 * math.exp(z * sigma))


def test_pure_product_takes_analytic_path() -> None:
    r = magnitude.estimate([_f("a", 1, 2), _f("b", 3, 4, op="div")])
    assert r.method == magnitude.ANALYTIC


def test_any_additive_term_takes_monte_carlo_path() -> None:
    r = magnitude.estimate([_f("a", 10, 10), _f("b", 5, 5, op="add")])
    assert r.method == magnitude.MONTE_CARLO


def test_leading_signed_factor_takes_monte_carlo_path() -> None:
    # A leading add/sub opens a signed term the analytic closed form can't
    # represent (it only negates div), so it must route to Monte Carlo where
    # _terms carries the sign; otherwise the published magnitude loses its sign.
    r = magnitude.estimate([_f("a", 1, 10, op="sub"), _f("b", 2, 2)])
    assert r.method == magnitude.MONTE_CARLO
    assert r.median < 0  # the leading sub makes the term negative


def test_monte_carlo_is_deterministic_under_a_fixed_seed() -> None:
    factors = [_f("a", 10, 40), _f("b", 5, 5, op="add")]
    one = magnitude.estimate(factors, mc_samples=20000, mc_seed=1729)
    two = magnitude.estimate(factors, mc_samples=20000, mc_seed=1729)
    assert (one.median, one.low, one.high) == (two.median, two.low, two.high)


def test_monte_carlo_approximates_analytic_on_a_pure_product() -> None:
    # The MC path, run on a product, should land near the exact closed form.
    factors = [_f("a", 100, 400), _f("b", 2, 8)]
    exact = magnitude.propagate_lognormal(factors, ci=90.0)
    sampled = magnitude.propagate_montecarlo(factors, ci=90.0, samples=80000, seed=1729)
    assert math.isclose(sampled.median, exact.median, rel_tol=0.05)
    assert math.isclose(sampled.high, exact.high, rel_tol=0.10)


def test_dominant_factor_is_the_widest() -> None:
    # 'wide' spans a factor of 100; 'narrow' a factor of 2, so 'wide' dominates.
    r = magnitude.estimate([_f("narrow", 9, 18), _f("wide", 1, 100)])
    assert r.dominant_factor == "wide"
    shares = {s.factor_id: s.variance_share for s in r.factors}
    assert shares["wide"] > shares["narrow"]


def test_summed_subproducts_add_up() -> None:
    # (100 fixed) + (50 fixed) = 150, no spread since every factor is a point.
    factors = [_f("a", 100, 100), _f("b", 50, 50, op="add")]
    r = magnitude.estimate(factors, mc_samples=5000, mc_seed=1729)
    assert math.isclose(r.median, 150.0, rel_tol=1e-9)

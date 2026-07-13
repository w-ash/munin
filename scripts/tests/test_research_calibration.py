"""Pure-function tests for the calibration engine (reliability + conformal)."""

import math

import pytest

from vault_scripts.research import calibration


def test_bins_cover_unit_interval_with_last_bin_closed() -> None:
    report = calibration.reliability([(0.1, True), (1.0, True)])
    assert len(report.bins) == 10
    assert report.bins[1].n == 1  # 0.1 lands in [0.1, 0.2)
    assert report.bins[9].n == 1  # 1.0 lands in the closed last bin
    assert (report.bins[0].lower, report.bins[0].upper) == (0.0, 0.1)
    assert (report.bins[9].lower, report.bins[9].upper) == (0.9, 1.0)


def test_empty_bins_stay_visible() -> None:
    report = calibration.reliability([(0.55, True)])
    empty = [b for b in report.bins if b.n == 0]
    assert len(empty) == 9
    assert all(b.mean_probability is None and b.hit_rate is None for b in empty)


def test_ece_and_brier_hand_computed() -> None:
    # One bin [0.8, 0.9): mean p 0.8, hit rate 0.5 -> ECE = |0.5 - 0.8| = 0.3.
    report = calibration.reliability([(0.8, True), (0.8, False)])
    assert report.n == 2
    assert report.ece == 0.3
    assert report.brier == 0.34  # ((0.8 - 1)^2 + 0.8^2) / 2


def test_perfectly_calibrated_scores_zero() -> None:
    report = calibration.reliability([(0.0, False), (1.0, True)])
    assert report.ece == 0.0
    assert report.brier == 0.0


def test_out_of_range_probability_rejected() -> None:
    with pytest.raises(ValueError, match="out of range"):
        calibration.reliability([(1.2, True)])


def test_empty_pairs_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        calibration.reliability([])


def test_conformal_quantile_finite_sample_rank() -> None:
    # n=20, alpha=0.1: rank ceil(21 * 0.9) = 19 -> the 19th smallest score.
    scores = [i / 100 for i in range(1, 21)]  # 0.01 .. 0.20
    assert calibration.conformal_quantile(scores, 0.1) == 0.19


def test_conformal_quantile_small_set_raises() -> None:
    # n=5, alpha=0.1: rank ceil(6 * 0.9) = 6 > 5, no valid quantile exists.
    with pytest.raises(ValueError, match="too small"):
        calibration.conformal_quantile([0.1] * 5, 0.1)


def test_conformal_quantile_bad_alpha_raises() -> None:
    with pytest.raises(ValueError, match="alpha"):
        calibration.conformal_quantile([0.1] * 30, 0.0)


def test_binary_scores() -> None:
    # 1 - p when the label is true, p when false: how wrong was p.
    assert calibration.binary_scores([(0.75, True), (0.2, False)]) == [0.25, 0.2]


def test_standardized_log_residuals() -> None:
    triples = [(0.0, 1.0, math.e), (0.0, 2.0, 1.0)]
    assert calibration.standardized_log_residuals(triples) == [1.0, 0.0]


def test_log_residual_guards() -> None:
    with pytest.raises(ValueError, match="sigma"):
        calibration.standardized_log_residuals([(0.0, 0.0, 1.0)])
    with pytest.raises(ValueError, match="actual"):
        calibration.standardized_log_residuals([(0.0, 1.0, 0.0)])


def test_conformal_log_interval() -> None:
    # median * exp(-+ q_hat * sigma_total), 4 significant figures.
    low, high = calibration.conformal_log_interval(100.0, 0.5, 2.0)
    assert (low, high) == (36.79, 271.8)

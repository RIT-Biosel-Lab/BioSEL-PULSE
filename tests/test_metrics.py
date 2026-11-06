"""Unit tests for core PAM metrics.

Run with:  uv run pytest
           uv run pytest -v tests/test_metrics.py
Author's Note: I got curious in here, it kinda works, but I wouldnt give too much thought in here, a lot of this was just
me bolting on what Python 101 or internet gave me, plus some MATLAB self knowledge than me asking someone for help :c
"""

import numpy as np
import pandas as pd
import pytest

from pam_metric_analysis import (
    _polyarea,
    centroid_drift_sum,
    ellipse_metric_for_centroid,
    combined_polyarea_normalization,
)


# -- Helpers


def _scatter_cycles(n_cycles: int = 5, pts: int = 8, seed: int = 42) -> pd.DataFrame:
    """Synthetic cycles whose centroids spread across (P, X) space."""
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(1, n_cycles + 1):
        for _ in range(pts):
            rows.append(
                {
                    "Pressure": (10 + c * 5) + rng.normal(0, 0.5),
                    "Contraction": (5 + c * 2) + rng.normal(0, 0.3),
                    "Cycle": c,
                    "Time_s": 0.0,
                }
            )
    return pd.DataFrame(rows)


def _ellipse_cycles(n_cycles: int = 5, pts: int = 30) -> pd.DataFrame:
    """Cycles that trace a proper hysteresis ellipse - guaranteed non-zero area."""
    theta = np.linspace(0, 2 * np.pi, pts, endpoint=False)
    rows = []
    for c in range(1, n_cycles + 1):
        p_vals = (10 + c * 2) + 5 * np.cos(theta)
        x_vals = (10 + c * 1) + 3 * np.sin(theta)
        for i in range(pts):
            rows.append(
                {
                    "Pressure": p_vals[i],
                    "Contraction": x_vals[i],
                    "Cycle": c,
                    "Time_s": 0.0,
                }
            )
    return pd.DataFrame(rows)


# -- 1. _polyarea


class TestPolyarea:
    def test_unit_square(self):
        p = np.array([0.0, 1.0, 1.0, 0.0])
        x = np.array([0.0, 0.0, 1.0, 1.0])
        assert _polyarea(p, x) == pytest.approx(1.0)

    def test_right_triangle(self):
        # base=4, height=3 → area=6
        p = np.array([0.0, 4.0, 0.0])
        x = np.array([0.0, 0.0, 3.0])
        assert _polyarea(p, x) == pytest.approx(6.0)

    def test_collinear_points_zero_area(self):
        p = np.array([0.0, 1.0, 2.0])
        x = np.array([0.0, 1.0, 2.0])
        assert _polyarea(p, x) == pytest.approx(0.0)


# -- 2. centroid_drift_sum


class TestCentroidDriftSum:
    def test_clean_cycles_returns_valid_centroids(self):
        df = _scatter_cycles(n_cycles=5, pts=8)
        results, summary, outlier_idx = centroid_drift_sum(df)

        assert len(results) == 5
        assert not results["Centroid_Pressure"].isna().all()
        assert not results["Centroid_Pot"].isna().all()
        # Centroids should track cycle means (each cycle is centered higher)
        assert (
            results["Centroid_Pressure"].iloc[0] < results["Centroid_Pressure"].iloc[-1]
        )

    def test_all_identical_values_no_crash(self):
        """Singular covariance (all centroids equal) must not raise."""
        rows = [
            {"Pressure": 20.0, "Contraction": 10.0, "Cycle": c, "Time_s": 0.0}
            for c in range(1, 6)
            for _ in range(5)
        ]
        df = pd.DataFrame(rows)
        results, summary, outlier_idx = centroid_drift_sum(df)

        assert len(results) == 5
        assert results["Centroid_Pressure"].nunique() == 1
        assert results["Centroid_Pot"].nunique() == 1

    def test_short_cycles_produce_nan_centroids_no_crash(self):
        """Cycles with <=2 points → NaN centroids, should not raise."""
        rows = [
            {"Pressure": 20.0, "Contraction": 10.0, "Cycle": c, "Time_s": 0.0}
            for c in range(1, 4)
            for _ in range(2)  # only 2 points - below the len > 2 guard
        ]
        df = pd.DataFrame(rows)
        results, summary, outlier_idx = centroid_drift_sum(df)

        assert len(results) == 3
        assert results["Centroid_Pressure"].isna().all()
        assert results["Centroid_Pot"].isna().all()


# -- 3. ellipse_metric_for_centroid


class TestEllipseMetric:
    def test_clean_centroid_cloud_has_positive_area(self):
        df = _scatter_cycles(n_cycles=10, pts=8)
        cent_df, _, _ = centroid_drift_sum(df)
        result = ellipse_metric_for_centroid(cent_df)

        assert not np.isnan(result["area"])
        assert result["area"] > 0

    def test_all_nan_centroids_returns_nan_not_crash(self):
        """All-NaN input (upstream centroid failure) must return NaN dict, not raise."""
        nan_df = pd.DataFrame(
            {
                "Centroid_Pressure": [np.nan, np.nan, np.nan, np.nan],
                "Centroid_Pot": [np.nan, np.nan, np.nan, np.nan],
            }
        )
        result = ellipse_metric_for_centroid(nan_df)
        assert np.isnan(result["area"])

    def test_empty_dataframe_returns_nan(self):
        empty_df = pd.DataFrame(columns=["Centroid_Pressure", "Centroid_Pot"])
        result = ellipse_metric_for_centroid(empty_df)
        assert np.isnan(result["area"])

    def test_single_row_returns_nan(self):
        one_row = pd.DataFrame(
            {
                "Centroid_Pressure": [15.0],
                "Centroid_Pot": [10.0],
            }
        )
        result = ellipse_metric_for_centroid(one_row)
        assert np.isnan(result["area"])


# -- 4. combined_polyarea_normalization


class TestCombinedPolyarea:
    def test_empty_dataframe_returns_nan(self):
        empty_df = pd.DataFrame(columns=["Pressure", "Contraction", "Cycle", "Time_s"])
        results, summary, norm = combined_polyarea_normalization(empty_df)

        assert np.isnan(summary["LoopArea_mean"].iloc[0])
        assert np.isnan(norm["comDen"].iloc[0])

    def test_ellipse_loops_have_known_area(self):
        """Ellipses with semi-axes 5 and 3 → per-cycle area ≈ π·5·3 ≈ 47.1."""
        df = _ellipse_cycles(n_cycles=5, pts=200)
        results, summary, norm = combined_polyarea_normalization(df)

        assert not np.isnan(summary["LoopArea_mean"].iloc[0])
        expected = np.pi * 5 * 3
        assert summary["LoopArea_mean"].iloc[0] == pytest.approx(expected, rel=0.01)

"""Diagnose why specific datasets produce NaN ellipse areas.

Point this at a folder containing the known-bad CSV files (or even a single
subfolder).  It runs the exact same pipeline steps as run_analysis.py but
prints a step-by-step trace for every dataset so you can see which guard
fired and why.

Usage:
    uv run python tools/diagnose_nan_ellipse.py  Data/MyBadFolder/
    uv run python tools/diagnose_nan_ellipse.py  Data/MyBadFolder/  --active-len 6

This was added because I was trying to figure out why some CSV were producing NaN for some of the metrics during analysis.
"""

import argparse
import sys
from pathlib import Path

# Make core/ importable regardless of working directory
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import numpy as np
import pandas as pd
from pam_metric_analysis import (
    _load_data_files,
    cycle_snapshots,
    cycle_active_loop,
    centroid_drift_sum,
    ellipse_metric_for_centroid,
)


def _diagnose_one(
    name: str, table: pd.DataFrame, active_len: float, delta_p: float
) -> None:
    print(f"\n{'=' * 64}")
    print(f"  {name}")
    print(f"{'=' * 64}")

    # -- rename columns to internal names -
    df = table.rename(
        columns={"Pressure_psi": "Pressure", "Pot_percent": "Contraction"}
    )

    total_rows = len(df)
    cycle_counts = df["Cycle"].value_counts().sort_index()
    n_cycles = cycle_counts.shape[0]
    print(f"  Rows: {total_rows}   Cycles found: {n_cycles}")

    short_cycles = cycle_counts[cycle_counts <= 2]
    if not short_cycles.empty:
        print(
            f"  [WARN] Cycles with <=2 pts ({len(short_cycles)} of {n_cycles}): "
            f"{short_cycles.index.tolist()[:10]}{'...' if len(short_cycles) > 10 else ''}"
        )
    else:
        print(f"  [ok] All cycles have >2 pts")

    # -- standard pipeline to feedstock -
    try:
        snapped = cycle_snapshots(df, step=1, start_cycle=1, end_cycle=120)
        feedstock = cycle_active_loop(snapped, active_len=active_len, delta_p=delta_p)
        print(
            f"  After cycle_active_loop: {len(feedstock)} rows, "
            f"{feedstock['Cycle'].nunique()} cycles"
        )
    except Exception as exc:
        print(f"  [X] Pipeline failed before centroid step: {exc}")
        return

    # -- centroid_drift_sum - manual trace
    print()
    print("  [ centroid_drift_sum ]")

    all_cycles = np.unique(feedstock["Cycle"].values)
    n = len(all_cycles)
    centroid_x = np.full(n, np.nan)
    centroid_y = np.full(n, np.nan)

    short_after_filter = []
    for i, c in enumerate(all_cycles):
        mask = feedstock["Cycle"] == c
        p = feedstock.loc[mask, "Pressure"].values
        x = feedstock.loc[mask, "Contraction"].values
        if len(p) > 2:
            centroid_x[i] = np.mean(p)
            centroid_y[i] = np.mean(x)
        else:
            short_after_filter.append((c, len(p)))

    nan_cx = int(np.isnan(centroid_x).sum())
    nan_cy = int(np.isnan(centroid_y).sum())

    if short_after_filter:
        print(
            f"  [WARN] {len(short_after_filter)} cycle(s) still <=2 pts after active-loop filter "
            f"-> NaN centroids: {short_after_filter[:5]}{'...' if len(short_after_filter) > 5 else ''}"
        )
    else:
        print(f"  [ok] All cycles had >2 pts after filter")

    print(f"  NaN centroids - Pressure: {nan_cx}/{n}   Contraction: {nan_cy}/{n}")

    xmat = np.column_stack([centroid_x, centroid_y])
    cov = np.cov(xmat.T)
    print(f"  Covariance matrix:\n    {cov}")

    if np.any(np.isnan(cov)):
        print(
            "  [WARN] NaN covariance -> centroid_drift_sum guard fires (all-NaN centroids path)"
        )
    elif np.allclose(cov, 0):
        print(
            "  [WARN] Near-zero covariance -> centroid_drift_sum guard fires (all-identical centroids path)"
        )
    else:
        print("  [ok] Covariance is non-degenerate")

    # -- run actual function to get the real centroid results -
    try:
        cent_df, _, outlier_idx = centroid_drift_sum(feedstock)
        n_outliers = len(outlier_idx)
        good = n - n_outliers
        print(f"  Mahalanobis: {n_outliers} outlier(s), {good} inlier(s)")
        if good <= 1:
            print(f"  [WARN] good_idx has <=1 entry -> interpolation undefined")
    except Exception as exc:
        print(f"  [X] centroid_drift_sum raised: {exc}")
        return

    # -- ellipse_metric_for_centroid - manual trace -
    print()
    print("  [ ellipse_metric_for_centroid ]")

    x = cent_df[["Centroid_Pressure", "Centroid_Pot"]].values
    valid = x[~np.isnan(x).any(axis=1)]
    print(f"  Valid (non-NaN) centroid rows: {len(valid)} of {len(x)}")

    if len(valid) < 2:
        print(f"  [WARN] ellipse guard fires -> returns NaN area")
        root_cause = (
            "all cycles had <=2 points"
            if short_after_filter
            else "near-zero covariance (identical centroids)"
        )
        print(f"  Root cause: {root_cause}")
    else:
        try:
            result = ellipse_metric_for_centroid(cent_df)
            area = result["area"]
            if np.isnan(area):
                print(
                    f"  [WARN] ellipse area = NaN even with {len(valid)} valid rows - unexpected"
                )
            else:
                print(
                    f"  [ok] ellipse area = {area:.6f}   eccentricity = {result['eccentricity']:.4f}"
                )
        except Exception as exc:
            print(f"  [X] ellipse_metric_for_centroid raised: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose NaN ellipse areas in known-bad datasets"
    )
    parser.add_argument("data_path", help="Folder containing the bad CSV files")
    parser.add_argument(
        "--active-len",
        type=float,
        default=6.0,
        help="Active pressurization window (s), default 6.0",
    )
    parser.add_argument(
        "--delta-p",
        type=float,
        default=3.44738,
        help="Pressure threshold above baseline (kPa), default 3.44738",
    )
    args = parser.parse_args()

    path = Path(args.data_path)
    if not path.exists():
        print(f"Path not found: {path}")
        sys.exit(1)

    print(f"Loading from: {path}")
    try:
        tables, source_meta, _ = _load_data_files(path)
    except Exception as exc:
        print(f"Failed to load: {exc}")
        sys.exit(1)

    print(f"Loaded {len(tables)} dataset(s)")

    for name, table in tables.items():
        _diagnose_one(name, table, args.active_len, args.delta_p)

    print(f"\nDone - {len(tables)} dataset(s) checked.")


if __name__ == "__main__":
    main()

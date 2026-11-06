"""PAM Metric Analysis for BioSEL synthetic data.

Port of PAM_MetricAnalysisCombined.m from MATLAB (Internal and preliminary, use Python as the reference for analysis).
Analyzes pneumatic artificial muscle (PAM) actuation cycles: hysteresis loops,
centroid drift, cycle-to-cycle correlation, and modal distribution testing.

Supports CSV folder input:
  - CSV folders: one folder per experiment, searched recursively

Pipeline:
  1. Load data from a CSV folder with 4-column tables [Time, Pressure, Contraction, Cycle]
  2. Filter cycles and extract active pressurization windows
  3. Compute loop areas, centroid drift metrics, correlation distributions
  4. Computes 95% conf. ellipse area (Centroid Drift that tracks centroids of hysteresis)
  5. Run Hartigan's dip test on correlation distributions

-- Author's Note --
This py file was ported originally from MATLAB which was done during the time of M.S. Thesis within BioSEL
"""

from __future__ import annotations

import os
import sys
import warnings
import yaml
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats, interpolate
from sklearn.linear_model import LinearRegression
from compute_derived_metrics import compute_derivatives
from user_metrics import compute_user_metrics


def configure_console() -> None:
    """Make stdout/stderr tolerant of any character, on any platform.

    On Windows the default encoding of a redirected stream is the ANSI code page
    (usually cp1252), which cannot represent characters this pipeline may echo
    back from a filename or a config file. Without this, `> log.txt` turns a
    successful run into a UnicodeEncodeError. Called from the entry point of
    every script and from each worker process, since a spawned worker gets fresh
    stream objects. (Author's Notes: This was me trying to figure out differences in csv with fonts and unicode errors)
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass


def _find_csv_header_row(filepath: Path) -> int:
    """Return the 0-indexed line number where the CSV header starts, or -1 if not found.

    Skips BioSEL DAQ marker lines and Humidity/Temperature metadata rows.
    Author's Note: This is where such modifications could be gleaned, if you want temperatures, this is a great place to add and track
    potential temperatures of the room or possibly let say ambient temperature within the muscle and pressure manifolds
    Example 1: You run a batch of let say 4 different run, you can track the temperature in this way.

    However, this works for at the time the run works as it was recording when starting, that being said: This could be something worth exploring. This
    metric is experimental.
    """
    lines = None
    for encoding in ["utf-8", "latin-1"]:
        try:
            with open(filepath, "r", encoding=encoding) as f:
                lines = f.readlines()
            break
        except UnicodeDecodeError:
            continue
        except Exception:
            return -1

    if lines is None:
        return -1

    _markers = [
        "=== this is the start of a new run ===",
        "=== begin mckibben data ===",
    ]
    _header_starts = ("Time_s,", "Time(s),")

    marker_idx = None
    for i, line in enumerate(lines):
        ll = line.lower()
        if any(m in ll for m in _markers):
            marker_idx = i
            break

    header_idx = None

    if marker_idx is not None:
        for i in range(marker_idx + 1, len(lines)):
            line = lines[i].strip()
            if not line:
                continue
            if "humidity" in line.lower() or "temperature" in line.lower():
                continue
            header_idx = i
            break
    else:
        for i, line in enumerate(lines):
            stripped = line.strip()
            if any(stripped.startswith(h) for h in _header_starts):
                header_idx = i
                break

    return header_idx if header_idx is not None else -1


def _load_data_files(
    data_source: str | Path,
) -> tuple[dict[str, pd.DataFrame], dict[str, str], dict[str, Path]]:
    """Load all CSVs from a directory (recursive). Each must have 4 columns: Time_s, Pressure_psi, Pot_percent, Cycle.

    Returns (tables_dict, source_metadata, folder_paths_dict).
    """
    data_source = Path(data_source)
    tables = {}
    source_metadata = {}
    folder_paths = {}

    if data_source.is_dir():
        # Recursively find all CSV files in directory tree
        for csv_file in sorted(data_source.rglob("*.csv")):
            rel_path = csv_file.relative_to(data_source)
            # Dataset name: flatten path with underscores (e.g., Folder1_Subfolder_File)
            dataset_name = str(rel_path.with_suffix("").as_posix()).replace("/", "_")
            if dataset_name == "arr":
                continue

            # Find the actual header row (skip metadata lines)
            header_row = _find_csv_header_row(csv_file)
            if header_row == -1:
                print(f"Skipping {rel_path}: Could not find header")
                continue

            try:
                # Try multiple encodings: UTF-8, Latin-1, Windows, ASCII with errors='replace'
                df = None
                encodings_to_try = ["utf-8", "latin-1", "cp1252", "iso-8859-1"]
                last_error = None

                for encoding in encodings_to_try:
                    try:
                        df = pd.read_csv(
                            csv_file,
                            encoding=encoding,
                            skiprows=header_row,
                            low_memory=False,
                        )
                        # Normalise new DAQ format column names to legacy names
                        if df is not None:
                            df = df.rename(
                                columns={
                                    "Time(s)": "Time_s",
                                    "Pressure(psi)": "Pressure_psi",
                                    "Potentiometer(%)": "Pot_percent",
                                    "Cycle(-)": "Cycle",
                                }
                            )
                        # Convert columns to correct types with error handling
                        if (
                            df is not None
                            and not df.empty
                            and all(
                                col in df.columns
                                for col in [
                                    "Time_s",
                                    "Pressure_psi",
                                    "Pot_percent",
                                    "Cycle",
                                ]
                            )
                        ):
                            df["Time_s"] = pd.to_numeric(df["Time_s"], errors="coerce")
                            df["Pressure_psi"] = pd.to_numeric(
                                df["Pressure_psi"], errors="coerce"
                            )
                            df["Pot_percent"] = pd.to_numeric(
                                df["Pot_percent"], errors="coerce"
                            )
                            # For Cycle, use float to handle NaN gracefully
                            df["Cycle"] = pd.to_numeric(df["Cycle"], errors="coerce")
                        break
                    except Exception as e:
                        last_error = e
                        df = None
                        continue

                # Last resort: read WITHOUT dtype spec (let pandas infer), then convert
                if df is None:
                    try:
                        df = pd.read_csv(
                            csv_file,
                            encoding="utf-8",
                            encoding_errors="replace",
                            skiprows=header_row,
                            low_memory=False,
                        )
                        # Normalise new DAQ format column names to legacy names
                        if df is not None:
                            df = df.rename(
                                columns={
                                    "Time(s)": "Time_s",
                                    "Pressure(psi)": "Pressure_psi",
                                    "Potentiometer(%)": "Pot_percent",
                                    "Cycle(-)": "Cycle",
                                }
                            )
                        # Convert columns to correct types with error handling
                        if (
                            df is not None
                            and not df.empty
                            and all(
                                col in df.columns
                                for col in [
                                    "Time_s",
                                    "Pressure_psi",
                                    "Pot_percent",
                                    "Cycle",
                                ]
                            )
                        ):
                            df["Time_s"] = pd.to_numeric(df["Time_s"], errors="coerce")
                            df["Pressure_psi"] = pd.to_numeric(
                                df["Pressure_psi"], errors="coerce"
                            )
                            df["Pot_percent"] = pd.to_numeric(
                                df["Pot_percent"], errors="coerce"
                            )
                            # For Cycle, use float to handle NaN gracefully
                            df["Cycle"] = pd.to_numeric(df["Cycle"], errors="coerce")
                    except Exception as e:
                        last_error = e
                        df = None

                if df is None:
                    print(
                        f"Skipping {rel_path}: {type(last_error).__name__}: {last_error}"
                    )
                    continue

                # Check for .metadata.yaml and apply conversions (walk up folder tree)
                current = csv_file.parent
                metadata_file = None
                while current != current.parent:
                    candidate = current / ".metadata.yaml"
                    if candidate.exists():
                        metadata_file = candidate
                        break
                    current = current.parent

                if metadata_file is not None:
                    try:
                        with open(metadata_file, "r", encoding="utf-8") as f:
                            config = yaml.safe_load(f)
                        bypass_val = (config or {}).get("bypass", False)
                        if isinstance(bypass_val, str):
                            bypass_val = bypass_val.strip().lower() == "true"
                        if bypass_val:
                            print(
                                f"  Bypassing {rel_path} (bypass flag set in {metadata_file.name})"
                            )
                            continue
                        if config and config.get("processed") is False:
                            conversions = config.get("conversions", {})
                            if conversions.get("psi_to_kpa"):
                                df["Pressure_psi"] = df["Pressure_psi"] * 6.89476
                            if conversions.get("pot_percent_scale_factor"):
                                scale_factor = conversions["pot_percent_scale_factor"]
                                df["Pot_percent"] = df["Pot_percent"] * scale_factor
                    except Exception as e:
                        print(f"  Warning: Could not read .metadata.yaml: {e}")

                if df.shape[1] == 4:
                    tables[dataset_name] = df
                    # Store full relative path showing folder hierarchy
                    source_metadata[dataset_name] = str(
                        rel_path.with_suffix("").as_posix()
                    )
                    # Store folder path for active_loop config lookup
                    folder_paths[dataset_name] = csv_file.parent
                else:
                    print(f"Skipping {rel_path}: Expected 4 columns, got {df.shape[1]}")
            except Exception as e:
                print(f"Skipping {rel_path}: {e}")

    else:
        raise FileNotFoundError(
            f"{data_source} is not a directory. Expected a folder containing CSV files.\n"
            "Pass the folder that holds the CSVs (it is searched recursively), not a single file."
        )

    if not tables:
        csvs = sorted(data_source.rglob("*.csv"))
        lines = [f"No usable CSV datasets found in {data_source}"]
        if not csvs:
            lines += [
                "",
                "That folder contains no .csv files at all (searched recursively).",
                "  - Check the path you passed on the command line.",
                "  - On Windows, check that the archive actually finished extracting:",
                "    a 'Path too long' error during extraction silently leaves folders empty.",
                "    Extract to a short path such as C:\\BioSEL and try again.",
            ]
        else:
            lines += [
                "",
                f"Found {len(csvs)} .csv file(s), but none had the 4 expected columns.",
                "Expected (either spelling is accepted):",
                "  Time_s, Pressure_psi, Pot_percent, Cycle",
                "  Time(s), Pressure(psi), Potentiometer(%), Cycle(-)",
                "",
                "First file inspected: " + str(csvs[0].relative_to(data_source)),
            ]
            header_row = _find_csv_header_row(csvs[0])
            if header_row == -1:
                lines.append("  No header row was recognised in it.")
            else:
                try:
                    with open(csvs[0], "r", encoding="utf-8", errors="replace") as fh:
                        found = fh.readlines()[header_row].strip()
                    lines.append(f"  Header found instead: {found}")
                except OSError:
                    pass
        raise ValueError("\n".join(lines))

    return tables, source_metadata, folder_paths


def cycle_snapshots(
    df: pd.DataFrame,
    step: int = 1,
    start_cycle: int = 1,
    end_cycle: int = 120,
) -> pd.DataFrame:
    """Filter table by cycle numbers, select cycles at given stride.

    Args:
        df: DataFrame with columns including Cycle
        step: Cycle stride for snapshot selection
        start_cycle: First cycle to include
        end_cycle: Last cycle to include

    Returns:
        Filtered DataFrame
    """
    start_cycle = max(1, round(start_cycle))
    end_cycle = min(120, round(end_cycle))

    cycles = np.arange(start_cycle, end_cycle + 1, step, dtype=int)
    if end_cycle >= 120 and 120 not in cycles:
        cycles = np.append(cycles, 120)

    mask = df["Cycle"].isin(cycles)
    return df[mask].reset_index(drop=True)


def detect_active_window(
    window_df: pd.DataFrame,
    delta_p: float = 0.5,
    baseline: float | None = None,
) -> tuple[float, float]:
    """Auto-detect pressure rise window bounds within a single time window.

    Finds where pressure crosses baseline + delta_p, then where it drops back.
    Returns offsets relative to the window's start time, suitable for use as
    active_start and active_end in time_snapshots().

    Args:
        window_df: DataFrame containing a single time window (Cycle == 1)
        delta_p: Pressure threshold above baseline to define rise
        baseline: Baseline pressure (if None, computed from first 15s of data)

    Returns:
        (active_start_s, active_end_s): offsets in seconds from window start

    Raises:
        ValueError: If detection fails (no pressure rise detected, malformed data, etc)
    """
    if window_df.empty:
        raise ValueError("window_df is empty")

    time = window_df["Time_s"].values
    press = window_df["Pressure"].values

    if len(time) == 0:
        raise ValueError("No data in window")

    t_rel = time - time.min()

    if baseline is None:
        baseline = np.median(press)

    i_rise = np.where(press > baseline + delta_p)[0]
    if len(i_rise) == 0:
        raise ValueError(
            f"No pressure rise detected (baseline={baseline:.2f}, threshold={delta_p})"
        )

    i_start = i_rise[0]
    i_end = i_rise[-1]

    i_drop = np.where(press[i_end:] <= baseline + delta_p / 2)[0]
    if len(i_drop) > 0:
        i_end = i_end + i_drop[0]

    active_start = float(t_rel[i_start])
    active_end = float(t_rel[i_end])

    if active_end <= active_start:
        raise ValueError(
            f"Invalid window bounds: start={active_start:.2f}s >= end={active_end:.2f}s"
        )

    return (active_start, active_end)


def time_snapshots(
    df: pd.DataFrame,
    window_size_s: float = 10.0,
    max_time: float | None = None,
    active_start: float | None = None,
    active_end: float | None = None,
) -> pd.DataFrame:
    """Create fixed-duration time-window groups, replacing the Cycle column.

    Assigns a 1-based window index so all downstream metric functions work
    unchanged. Window 1 = [0, window_size_s), Window 2 = [window_size_s, 2*window_size_s), etc.
    Use this instead of cycle_snapshots when the Cycle column is unreliable
    or when the experimental period is known but cycle boundaries are offset
    (e.g. pressure rises at t=0.333 but cycle counter flips at t=10.000).

    Optionally restrict to a sub-window within each period using active_start
    and active_end (both in seconds, relative to the start of each window).
    Examples for a 10s period:
      active_start=0, active_end=6   -> keeps t=0-6, 10-16, 20-26, ...
      active_start=3, active_end=6   -> keeps t=3-6, 13-16, 23-26, ...
      omit both                      -> keeps the full window

    Args:
        df: DataFrame with Time_s column
        window_size_s: Duration of each time window in seconds
        max_time: If set, drop rows where elapsed time >= max_time (seconds)
        active_start: Seconds into each window to start keeping rows (default 0)
        active_end: Seconds into each window to stop keeping rows (default window_size_s)

    Returns:
        DataFrame with Cycle column overwritten by 1-based window index

    Author's Notes: Originally this was meant to track hysteresis active window, but nowadays can be scoped
    for any specific timings you want, it is maintained however that such scope outside hysteresis window break the computation
    of the fourth wall (you clever child) or that metrics further down the chain will break.
    """
    df = df.copy()
    t_rel = df["Time_s"].values - df["Time_s"].min()

    # Drop rows with NaN Time_s before any arithmetic
    valid_t = ~np.isnan(t_rel)
    if not np.all(valid_t):
        df = df[valid_t].copy()
        t_rel = t_rel[valid_t]

    if max_time is not None:
        mask = t_rel < float(max_time)
        df = df[mask].copy()
        t_rel = t_rel[mask]

    # Sub-window filter: keep only rows within [active_start, active_end) of each period
    a_start = float(active_start) if active_start is not None else 0.0
    a_end = float(active_end) if active_end is not None else float(window_size_s)
    t_within = t_rel % window_size_s
    sub_mask = (t_within >= a_start) & (t_within < a_end)
    df = df[sub_mask].copy()
    t_rel = t_rel[sub_mask]

    df["Cycle"] = (np.floor(t_rel / window_size_s) + 1).astype(int)
    return df.reset_index(drop=True)


def cycle_active_loop(
    df: pd.DataFrame,
    active_len: float = 6.0,
    delta_p: float = 0.5,
    backup_time: float = 0.5,
    start_cycle: int = 1,
    end_cycle: int = 120,
) -> pd.DataFrame:
    """Retain only rows within the active pressurization window of each cycle."""
    time = df["Time_s"].values
    press = df["Pressure"].values
    cycles = df["Cycle"].values

    baseline = np.median(press[time <= time.min() + 15])

    ucycles = np.unique(
        cycles[np.logical_and(cycles >= start_cycle, cycles <= end_cycle)]
    )
    keep = np.zeros(len(df), dtype=bool)

    for c in ucycles:
        idx_c = np.where(cycles == c)[0]
        if len(idx_c) == 0:
            continue

        tc = time[idx_c]
        pc = press[idx_c]

        i_rise = np.where(pc > baseline + delta_p)[0]
        if len(i_rise) == 0:
            continue
        i_rise = i_rise[0]

        t_start = tc[i_rise] - backup_time
        t_end = min(t_start + active_len, tc[-1])

        drop_idx = np.where(np.logical_and(tc > t_start, pc <= baseline + delta_p))[0]
        if len(drop_idx) > 0:
            t_end = min(t_end, tc[drop_idx[-1]])

        keep[idx_c[np.logical_and(tc >= t_start, tc <= t_end)]] = True

    return df[keep].reset_index(drop=True)


def _polyarea(p: np.ndarray, x: np.ndarray) -> float:
    """Shoelace formula for polygon area."""
    return 0.5 * float(np.abs(np.dot(p, np.roll(x, 1)) - np.dot(x, np.roll(p, 1))))


def combined_polyarea_normalization(
    df: pd.DataFrame, step: int = 1
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute per-cycle loop area, extrema percentiles, and normalization values.

    Returns (results_df, summary_df, normalization_df).
    Author's Note: Follow literature usage with Trapezoidal and Shoelace Theorems
    """
    if df.empty or "Cycle" not in df.columns:
        # Return empty results for degenerate data
        return (
            pd.DataFrame(
                columns=["Cycle", "LoopArea", "PeakPressure", "RestingX", "PeakX"]
            ),
            pd.DataFrame(
                {
                    "LoopArea_mean": [np.nan],
                    "LoopArea_std": [np.nan],
                    "LoopArea_min": [np.nan],
                    "LoopArea_max": [np.nan],
                    "LoopArea_median": [np.nan],
                }
            ),
            pd.DataFrame(
                {
                    "PressureNormalizeDelta": [np.nan],
                    "xNormalizeDelta": [np.nan],
                    "comDen": [np.nan],
                }
            ),
        )

    all_cycles = np.unique(df["Cycle"].values)
    cycles = all_cycles[::step]
    n_cycles = len(cycles)

    areas = np.full(n_cycles, np.nan)
    pmins = np.full(n_cycles, np.nan)
    p95s = np.full(n_cycles, np.nan)
    c5s = np.full(n_cycles, np.nan)
    c95s = np.full(n_cycles, np.nan)

    for i, c in enumerate(cycles):
        mask = df["Cycle"] == c
        p = df.loc[mask, "Pressure"].values
        x = df.loc[mask, "Contraction"].values

        if len(p) > 2 and len(x) > 2:
            areas[i] = _polyarea(p, x)
            pmin = np.median(p[p < 3]) if np.any(p < 3) else np.nanpercentile(p, 10)
            pmins[i] = pmin
            p95s[i] = np.nanpercentile(p, 95)
            c5s[i] = np.nanpercentile(x, 5)
            c95s[i] = np.nanpercentile(x, 95)

    results = pd.DataFrame(
        {
            "Cycle": cycles,
            "LoopArea": areas,
            "PeakPressure": p95s,
            "RestingX": c5s,
            "PeakX": c95s,
        }
    )

    # Safely compute summary stats (handle all-NaN case)
    valid_areas = areas[~np.isnan(areas)]
    if len(valid_areas) > 0:
        summary = pd.DataFrame(
            {
                "LoopArea_mean": [np.nanmean(areas)],
                "LoopArea_std": [np.nanstd(areas, ddof=1)],
                "LoopArea_min": [np.nanmin(valid_areas)],
                "LoopArea_max": [np.nanmax(valid_areas)],
                "LoopArea_median": [np.nanmedian(areas)],
            }
        )
    else:
        summary = pd.DataFrame(
            {
                "LoopArea_mean": [np.nan],
                "LoopArea_std": [np.nan],
                "LoopArea_min": [np.nan],
                "LoopArea_max": [np.nan],
                "LoopArea_median": [np.nan],
            }
        )

    # Guard against all-NaN values in normalization
    valid_c_diff = (c95s - c5s)[~np.isnan(c95s - c5s)]
    valid_p_diff = (p95s - 0.6205284)[~np.isnan(p95s - 0.6205284)]

    contraction_delta = np.nanmean(c95s - c5s) if len(valid_c_diff) > 0 else np.nan
    pressure_delta = np.nanmean(p95s - 0.6205284) if len(valid_p_diff) > 0 else np.nan
    com_den = (
        pressure_delta * contraction_delta
        if not (np.isnan(pressure_delta) or np.isnan(contraction_delta))
        else np.nan
    )

    normalization = pd.DataFrame(
        {
            "PressureNormalizeDelta": [pressure_delta],
            "xNormalizeDelta": [contraction_delta],
            "comDen": [com_den],
        }
    )

    return results, summary, normalization


def centroid_drift_sum(
    df: pd.DataFrame, step: int = 1
) -> tuple[pd.DataFrame, list[dict], np.ndarray]:
    """Compute per-cycle centroids with Mahalanobis outlier detection and interpolation.

    Returns (results_df, summary_list, outlier_indices).

    Author's Note: Refer to the companion papers of BioSEL for more information
    """
    if df.empty or "Cycle" not in df.columns:
        # Return empty results for degenerate data
        return (
            pd.DataFrame(columns=["Cycle", "Centroid_Pressure", "Centroid_Pot"]),
            [
                {
                    "mean": np.nan,
                    "std": np.nan,
                    "min": np.nan,
                    "max": np.nan,
                    "median": np.nan,
                },
                {
                    "mean": np.nan,
                    "std": np.nan,
                    "min": np.nan,
                    "max": np.nan,
                    "median": np.nan,
                },
            ],
            np.array([], dtype=int),
        )

    all_cycles = np.unique(df["Cycle"].values)
    cycles = all_cycles[::step]
    n_cycles = len(cycles)

    centroid_x = np.full(n_cycles, np.nan)
    centroid_y = np.full(n_cycles, np.nan)

    for i, c in enumerate(cycles):
        mask = df["Cycle"] == c
        p = df.loc[mask, "Pressure"].values
        x = df.loc[mask, "Contraction"].values
        if len(p) > 2:
            centroid_x[i] = np.mean(p)
        if len(x) > 2:
            centroid_y[i] = np.mean(x)

    xmat = np.column_stack([centroid_x, centroid_y])
    mu = np.mean(xmat, axis=0)
    cov = np.cov(xmat.T)
    # Degenerate covariance (all-NaN centroids or all-identical values): skip
    # Mahalanobis and treat every cycle as an inlier rather than inverting a
    # singular or NaN matrix.
    if np.any(np.isnan(cov)) or np.allclose(cov, 0):
        inv_cov = np.zeros_like(cov)
    else:
        try:
            inv_cov = np.linalg.inv(cov)
        except np.linalg.LinAlgError:
            inv_cov = np.linalg.pinv(cov)

    diff = xmat - mu
    md_sq = np.einsum("ij,jk,ik->i", diff, inv_cov, diff)

    thresh = stats.chi2.ppf(0.997, df=2)
    outlier_idx = np.where(md_sq > thresh)[0]
    good_idx = np.setdiff1d(np.arange(n_cycles), outlier_idx)

    xmat_interp = xmat.copy()
    for col in range(2):
        if len(outlier_idx) > 0 and len(good_idx) > 1:
            f = interpolate.interp1d(
                cycles[good_idx],
                xmat[good_idx, col],
                kind="linear",
                fill_value="extrapolate",
            )
            xmat_interp[outlier_idx, col] = f(cycles[outlier_idx])

    centroid_x = xmat_interp[:, 0]
    centroid_y = xmat_interp[:, 1]

    results = pd.DataFrame(
        {
            "Cycle": cycles,
            "Centroid_Pressure": centroid_x,
            "Centroid_Pot": centroid_y,
        }
    )

    # Safely compute summary (handle all-NaN case)
    valid_x = centroid_x[~np.isnan(centroid_x)]
    valid_y = centroid_y[~np.isnan(centroid_y)]

    summary = [
        {
            "mean": np.nanmean(centroid_x),
            "std": np.nanstd(centroid_x, ddof=1),
            "min": np.nanmin(valid_x) if len(valid_x) > 0 else np.nan,
            "max": np.nanmax(valid_x) if len(valid_x) > 0 else np.nan,
            "median": np.nanmedian(centroid_x),
        },
        {
            "mean": np.nanmean(centroid_y),
            "std": np.nanstd(centroid_y, ddof=1),
            "min": np.nanmin(valid_y) if len(valid_y) > 0 else np.nan,
            "max": np.nanmax(valid_y) if len(valid_y) > 0 else np.nan,
            "median": np.nanmedian(centroid_y),
        },
    ]

    return results, summary, outlier_idx


def ellipse_metric_for_centroid(results_df: pd.DataFrame) -> dict[str, Any]:
    """Fit a 95% confidence ellipse to the centroid cloud. Returns area, eccentricity, axes, and coords.
    Author's Note: This is something that will be discussed in a forthcoming paper circa late 2026 / 2027"""
    if results_df.empty or len(results_df) < 2:
        # Return NaN dict for degenerate data
        return {
            "area": np.nan,
            "mu": np.array([np.nan, np.nan]),
            "axes": np.array([np.nan, np.nan]),
            "eccentricity": np.nan,
            "ellipse_coords": np.array([]),
            "eigVec": np.array([]),
            "eigVal": np.array([]),
        }

    x = results_df[["Centroid_Pressure", "Centroid_Pot"]].values
    # Drop rows where either centroid is NaN before computing covariance;
    # otherwise np.cov returns a NaN matrix and the eigendecomposition produces
    # NaN axes silently rather than returning the explicit NaN sentinel below.
    # Author's Note: This is designed such that runs do not crash the loading.
    valid_rows = x[~np.isnan(x).any(axis=1)]
    if len(valid_rows) < 2:
        return {
            "area": np.nan,
            "mu": np.array([np.nan, np.nan]),
            "axes": np.array([np.nan, np.nan]),
            "eccentricity": np.nan,
            "ellipse_coords": np.array([]),
            "eigVec": np.array([]),
            "eigVal": np.array([]),
        }
    x = valid_rows
    n = len(x)
    mu = np.mean(x, axis=0)
    c = np.cov(x.T)

    eigval, eigvec = np.linalg.eigh(c)
    # Prieto et al. 1996, equation #18: AREA-CE = 2*pi*F(0.05; 2, n-2)*sqrt(det(C)) is what we are using.
    # Using F(0.05; 2, n-2) instead of the asymptotic chi-square value (chi2.ppf(0.95, df=2), the n -> inf limit of this F value),
    # so the area is exact for finite n rather than only accurate for large n.
    # This flew right under the radar originally, but now has been corrected.
    # Refer to forthcoming paper for more explanation or toward linked Zenodo / Lab GitHub accounts
    f_val = stats.f.ppf(0.95, 2, n - 2)
    axes_lengths = np.sqrt(2 * f_val * eigval)

    a = axes_lengths[0]
    b = axes_lengths[1]
    aa = np.max(axes_lengths)
    bb = np.min(axes_lengths)

    ellipse_area = np.pi * a * b
    eccentricity = np.sqrt(1.0 - (bb**2 / aa**2))

    theta = np.linspace(0, 2 * np.pi, 200)
    ellipse_pts = (
        eigvec @ np.diag(axes_lengths) @ np.array([np.cos(theta), np.sin(theta)])
    )
    ellipse_pts = ellipse_pts.T + mu

    return {
        "area": ellipse_area,
        "mu": mu,
        "axes": np.array([a, b]),
        "eccentricity": eccentricity,
        "ellipse_coords": ellipse_pts,
        "eigVec": eigvec,
        "eigVal": eigval,
    }


def cyc2cyc_corr_all(
    df: pd.DataFrame, npts: int = 200, min_overlap: float = 0.90
) -> pd.DataFrame:
    """Compute cycle-to-cycle Pearson correlation across 3 domains (Input-Time, Output-Time, Hysteresis)."""
    domains = [
        ("Time_s", "Pressure", "Input-Time"),
        ("Time_s", "Contraction", "Output-Time"),
        ("Pressure", "Contraction", "Hysteresis"),
    ]

    results_list = []

    for xcol, ycol, label in domains:
        cycles = np.unique(df["Cycle"].values)
        total_pairs = len(cycles) - 1
        corr_vals = []

        for k in range(total_pairs):
            cyc1 = df[df["Cycle"] == cycles[k]]
            cyc2 = df[df["Cycle"] == cycles[k + 1]]

            if len(cyc1) == 0 or len(cyc2) == 0:
                continue

            if xcol == "Time_s":
                x1 = cyc1[xcol].values - cyc1[xcol].min()
                y1 = cyc1[ycol].values
                x2 = cyc2[xcol].values - cyc2[xcol].min()
                y2 = cyc2[ycol].values

                x1, idx1 = np.unique(x1, return_index=True)
                y1 = y1[idx1]
                x2, idx2 = np.unique(x2, return_index=True)
                y2 = y2[idx2]

                xmin = 0
                xmax = min(np.max(x1), np.max(x2))
                xgrid = np.linspace(xmin, xmax, npts)
                y1i = np.interp(xgrid, x1, y1)
                y2i = np.interp(xgrid, x2, y2)
                do_pair = True
            else:
                x1, idx1 = np.unique(cyc1[xcol].values, return_index=True)
                y1 = cyc1[ycol].values[idx1]
                x2, idx2 = np.unique(cyc2[xcol].values, return_index=True)
                y2 = cyc2[ycol].values[idx2]

                x1_arr = np.asarray(x1, dtype=np.float64)
                y1_arr = np.asarray(y1, dtype=np.float64)
                x2_arr = np.asarray(x2, dtype=np.float64)
                y2_arr = np.asarray(y2, dtype=np.float64)

                x_global_min = min(np.min(x1_arr), np.min(x2_arr))
                x_global_max = max(np.max(x1_arr), np.max(x2_arr))
                global_span = x_global_max - x_global_min
                xmin = max(np.min(x1_arr), np.min(x2_arr))
                xmax = min(np.max(x1_arr), np.max(x2_arr))
                overlap_span = xmax - xmin
                do_pair = (
                    (overlap_span / global_span >= min_overlap)
                    if global_span > 0
                    else False
                )

                if do_pair:
                    xgrid = np.linspace(xmin, xmax, npts)
                    y1i = np.interp(xgrid, x1_arr, y1_arr)
                    y2i = np.interp(xgrid, x2_arr, y2_arr)

            if do_pair and np.std(y1i) > 0 and np.std(y2i) > 0:
                r = np.corrcoef(y1i, y2i)[0, 1]
                corr_vals.append(r)

        corr_vals = np.array(corr_vals)
        valid_count = len(corr_vals)

        res = pd.DataFrame(
            {
                "Domain": [label],
                "Xcol": [xcol],
                "Ycol": [ycol],
                "MeanCorr": [np.nanmean(corr_vals)],
                "StdCorr": [np.nanstd(corr_vals, ddof=1)],
                "ValidPairs": [valid_count],
                "TotalPairs": [total_pairs],
                "AllCorrVals": [[corr_vals]],
            }
        )

        print(
            f"Cycle-to-cycle correlation ({label}): {res['MeanCorr'].iloc[0]:.4f} +/- "
            f"{res['StdCorr'].iloc[0]:.4f} (N={valid_count} / {total_pairs})"
        )

        results_list.append(res)

    return pd.concat(results_list, ignore_index=True)


def avg_hyst_loop(df: pd.DataFrame, samples_per_cycle: int = 601) -> pd.DataFrame:
    """
    Compute mean ± std pressure/contraction trajectories resampled across all cycles.
    IMPORTANT: This is meant to visualize an average pathing of the McKibben Muscle's Hysteresis

    Author's Note: 601 is the legacy number from thesis works.
    This may be adjusted and should be dependent on how processing is setup for.
    I suggest you play with this, if this requires such rapid iteration or modifications, feel free to do so.
    """
    try:
        if isinstance(df, pd.DataFrame):
            data = df.values
        else:
            data = df

        pressure = data[:, 1]
        contraction = data[:, 2]
        n_cycles = int(np.floor(len(pressure) / samples_per_cycle))

        if n_cycles == 0:
            return pd.DataFrame()

        n_keep = samples_per_cycle * n_cycles
        pressure_mat = pressure[:n_keep].reshape(samples_per_cycle, n_cycles, order="F")
        contraction_mat = contraction[:n_keep].reshape(
            samples_per_cycle, n_cycles, order="F"
        )

        mean_pressure = np.mean(pressure_mat, axis=1)
        # Use ddof=0 if only 1 cycle (can't compute sample std with 1 sample)
        std_pressure = np.std(pressure_mat, axis=1, ddof=min(1, n_cycles - 1))
        mean_contraction = np.mean(contraction_mat, axis=1)
        std_contraction = np.std(contraction_mat, axis=1, ddof=min(1, n_cycles - 1))

        return pd.DataFrame(
            {
                "Pressure_mean": mean_pressure,
                "Pressure_std": std_pressure,
                "Contraction_mean": mean_contraction,
                "Contraction_std": std_contraction,
            }
        )
    except Exception:
        # Return empty DataFrame if computation fails (degenerate data)
        return pd.DataFrame()


def hartigans_dip_signif_test(
    xpdf: np.ndarray, nboot: int = 500
) -> tuple[float, float, float, float]:
    """Hartigan's dip statistic with bootstrap p-value. Returns (dip, p_value, xlow, xup).

    Author's Note: Below attributes the Hartigan's Dip Test code to F. Mechler and derived
    from his original MATLAB implementation.
    Calculates Hartigan's DIP statistic and bootstrap significance p-value.
    Code by F. Mechler (27 August 2002).

    """
    dip, xlow, xup = hartigans_dip_test(xpdf)
    n = len(xpdf)

    boot_dips = []
    for _ in range(nboot):
        unifpdf = np.sort(np.random.uniform(0, 1, n))
        boot_dips.append(hartigans_dip_test(unifpdf)[0])

    boot_dips = np.sort(boot_dips)
    p_val = np.sum(dip < boot_dips) / nboot

    return dip, p_val, xlow, xup


def hartigans_dip_test(xpdf: np.ndarray) -> tuple[float, float, float]:
    """Hartigan's dip test (AS 217, Appl. Statist. 1985). Returns (dip, xl, xu).

    Ported from FORTRAN via MATLAB. Uses 1-indexed arrays to stay faithful to the original.
    """
    x = np.sort(xpdf.flatten())
    n = len(x)

    if n <= 1:
        return 0.0, x[0] if len(x) > 0 else np.nan, x[-1] if len(x) > 0 else np.nan

    if n < 4:
        return 0.0, x[0], x[-1]

    if x[-1] <= x[0]:
        return 0.0, x[0], x[-1]

    xsign = -np.sign(np.diff(np.diff(x)))
    posi = np.where(xsign > 0)[0]
    negi = np.where(xsign < 0)[0]
    if len(posi) == 0 or len(negi) == 0:
        return 0.0, x[0], x[-1]
    if np.all(posi < np.min(negi)):
        return 0.0, x[0], x[-1]

    x1 = np.concatenate([[0.0], x])
    fn = float(n)

    mn = np.zeros(n + 1, dtype=int)
    mj = np.zeros(n + 1, dtype=int)
    lcm = np.zeros(n + 1, dtype=int)
    gcm = np.zeros(n + 1, dtype=int)

    low = 1
    high = n
    dip = 1.0 / fn
    xl = x1[low]
    xu = x1[high]

    mn[1] = 1
    for j in range(2, n + 1):
        mn[j] = j - 1
        mnj = mn[j]
        mnmnj = mn[mnj]
        a = mnj - mnmnj
        b = j - mnj
        while not (mnj == 1 or (x1[j] - x1[mnj]) * a < (x1[mnj] - x1[mnmnj]) * b):
            mn[j] = mnmnj
            mnj = mn[j]
            mnmnj = mn[mnj]
            a = mnj - mnmnj
            b = j - mnj

    mj[n] = n
    for jk in range(1, n):
        k = n - jk
        mj[k] = k + 1
        mjk = mj[k]
        mjmjk = mj[mjk]
        a = mjk - mjmjk
        b = k - mjk
        while not (mjk == n or (x1[k] - x1[mjk]) * a < (x1[mjk] - x1[mjmjk]) * b):
            mj[k] = mjmjk
            mjk = mj[k]
            mjmjk = mj[mjk]
            a = mjk - mjmjk
            b = k - mjk

    iterate = True
    while iterate:
        ic = 1
        gcm[1] = high
        while gcm[ic] > low:
            ic += 1
            gcm[ic] = mn[gcm[ic - 1]]
        icx = ic

        ic = 1
        lcm[1] = low
        while lcm[ic] < high:
            ic += 1
            lcm[ic] = mj[lcm[ic - 1]]
        icv = ic

        ig = icx
        ih = icv
        ix = icx - 1
        iv = 2
        d = 0.0

        if icx == 2 and icv == 2:
            d = 1.0 / fn
        else:
            iterate_bp50 = True
            while iterate_bp50:
                igcmx = gcm[ix]
                lcmiv = lcm[iv]

                if igcmx <= lcmiv:
                    lcmiv1 = lcm[iv - 1]
                    a = lcmiv - lcmiv1
                    b = igcmx - lcmiv1 - 1
                    dx = (x1[igcmx] - x1[lcmiv1]) * a / (
                        fn * (x1[lcmiv] - x1[lcmiv1])
                    ) - b / fn
                    ix -= 1
                    if dx >= d:
                        d = dx
                        ig = ix + 1
                        ih = iv
                else:
                    igcm = gcm[ix]
                    igcm1 = gcm[ix + 1]
                    a = lcmiv - igcm1 + 1
                    b = igcm - igcm1
                    dx = a / fn - (x1[lcmiv] - x1[igcm1]) * b / (
                        fn * (x1[igcm] - x1[igcm1])
                    )
                    iv += 1
                    if dx >= d:
                        d = dx
                        ig = ix + 1
                        ih = iv - 1

                if ix < 1:
                    ix = 1
                if iv > icv:
                    iv = icv

                iterate_bp50 = gcm[ix] != lcm[iv]

        iterate = d >= dip
        if iterate:
            dl = 0.0
            if ig != icx:
                for j in range(ig, icx):
                    temp = 1.0 / fn
                    jb = gcm[j + 1]
                    je = gcm[j]
                    if je - jb > 1 and x1[je] != x1[jb]:
                        a = je - jb
                        const = a / (fn * (x1[je] - x1[jb]))
                        for jr in range(jb, je + 1):
                            t = (jr - jb + 1) / fn - (x1[jr] - x1[jb]) * const
                            if t > temp:
                                temp = t
                    if dl < temp:
                        dl = temp

            du = 0.0
            if ih != icv:
                for k in range(ih, icv):
                    temp = 1.0 / fn
                    kb = lcm[k]
                    ke = lcm[k + 1]
                    if ke - kb > 1 and x1[ke] != x1[kb]:
                        a = ke - kb
                        const = a / (fn * (x1[ke] - x1[kb]))
                        for kr in range(kb, ke + 1):
                            t = (x1[kr] - x1[kb]) * const - (kr - kb - 1) / fn
                            if t > temp:
                                temp = t
                    if du < temp:
                        du = temp

            dipnew = max(dl, du)
            if dip < dipnew:
                dip = dipnew
            low = gcm[ig]
            high = lcm[ih]

    dip = 0.5 * dip
    xl = x1[low]
    xu = x1[high]

    return dip, xl, xu


def hartigans_dip_analysis(
    cyc2cyc_results: pd.DataFrame, nboot: int = 500, alpha: float = 0.05
) -> pd.DataFrame:
    """Run Hartigan's dip test on each correlation domain from cyc2cyc_corr_all. Discussed in companion paper"""
    n_domains = len(cyc2cyc_results)
    domains = cyc2cyc_results["Domain"].values
    dip_stats = np.full(n_domains, np.nan)
    p_values = np.full(n_domains, np.nan)
    is_sig = np.zeros(n_domains, dtype=bool)
    x_low = np.full(n_domains, np.nan)
    x_up = np.full(n_domains, np.nan)

    for d in range(n_domains):
        corr_vals = cyc2cyc_results.loc[d, "AllCorrVals"][0]
        corr_vals = corr_vals[~np.isnan(corr_vals)]

        if len(corr_vals) >= 4:
            dip, p_val, xl, xu = hartigans_dip_signif_test(corr_vals, nboot)
            dip_stats[d] = dip
            p_values[d] = p_val
            x_low[d] = xl
            x_up[d] = xu
            is_sig[d] = p_val < alpha
        else:
            dip, xl, xu = hartigans_dip_test(corr_vals)
            dip_stats[d] = dip
            x_low[d] = xl
            x_up[d] = xu

    return pd.DataFrame(
        {
            "Domain": domains,
            "DipStat": dip_stats,
            "p_value": p_values,
            "Significant": is_sig,
            "ModalLow": x_low,
            "ModalHigh": x_up,
        }
    )


def _process_one_dataset(packed: tuple) -> tuple:
    """Process a single dataset. Module-level function so ProcessPoolExecutor can pickle it."""
    (
        name,
        table,
        source_meta,
        folder_path,
        step_count,
        step_analysis,
        firstcyc,
        lastcyc,
        active_len,
        delta_p,
        backup_time,
        npts,
        min_overlap,
    ) = packed

    configure_console()

    result: dict = {}
    warnings_out: list = []

    try:
        meta: dict = {}
        al_config: dict = {}
        found_metadata_path = None
        if folder_path is not None:
            current = Path(folder_path)
            while current != current.parent:
                candidate = current / ".metadata.yaml"
                if candidate.exists():
                    found_metadata_path = candidate
                    try:
                        with open(candidate, "r", encoding="utf-8") as f:
                            meta = yaml.safe_load(f) or {}
                        al_config = meta.get("active_loop", {}) or {}
                        if meta.get("analysis_mode") or al_config:
                            print(f"  [{name}] Found config at {candidate}")
                    except Exception as e:
                        print(f"  [{name}] Warning: Could not read .metadata.yaml: {e}")
                    break
                current = current.parent

        analysis_mode = meta.get("analysis_mode", "cycle")
        tw_config = meta.get("time_window", {}) or {}

        al_active_len = al_config.get("active_len", active_len)
        al_delta_p = al_config.get("delta_p", delta_p)
        al_backup_time = al_config.get("backup_time", backup_time)
        skip_active = al_config.get("skip", False)
        derived_metrics_enabled = meta.get("derived_metrics", False)
        dm_config = meta.get("derived_metrics_config", {}) or {}
        smooth_window = int(dm_config.get("smooth_window", 5))
        smooth_method = str(dm_config.get("smooth_method", "rolling_mean"))
        butterworth_cutoff_hz = float(dm_config.get("butterworth_cutoff_hz", 10.0))
        butterworth_order = int(dm_config.get("butterworth_order", 4))
        complementary_alpha = float(dm_config.get("complementary_alpha", 0.3))
        bessel_cutoff_hz = float(dm_config.get("bessel_cutoff_hz", 10.0))
        bessel_order = int(dm_config.get("bessel_order", 4))
        hampel_threshold = float(dm_config.get("hampel_threshold", 3.0))
        wavelet_name = str(dm_config.get("wavelet_name", "db4"))
        wavelet_level = dm_config.get("wavelet_level", None)
        if wavelet_level is not None:
            wavelet_level = int(wavelet_level)
        wavelet_threshold_mode = str(dm_config.get("wavelet_threshold_mode", "soft"))
        tv_weight = float(dm_config.get("tv_weight", 0.1))
        loess_frac = float(dm_config.get("loess_frac", 0.1))
        kalman_process_noise = float(dm_config.get("kalman_process_noise", 1e-3))
        kalman_measurement_noise = float(dm_config.get("kalman_measurement_noise", 0.1))

        new_metrics_enabled = meta.get("new_metrics", False)
        nm_config = meta.get("new_metrics_config", {}) or {}
        _user_extra: dict = {}

        if analysis_mode == "time":
            window_size_s = float(tw_config.get("window_size_seconds", 10.0))
            max_time_s = tw_config.get("max_seconds", None)
            active_start = tw_config.get("active_start", None)
            active_end = tw_config.get("active_end", None)
            auto_detect = tw_config.get("auto_detect", False)
            if (
                auto_detect
                and active_start is None
                and active_end is None
                and not skip_active
            ):
                rough_res = time_snapshots(table, window_size_s, max_time_s, None, None)
                first_window = rough_res[rough_res["Cycle"] == 1]
                try:
                    detected_start, detected_end = detect_active_window(
                        first_window, al_delta_p
                    )
                    print(
                        f"  [{name}] [OK] Auto-detected active window: {detected_start:.2f}-{detected_end:.2f}s"
                    )
                    active_start, active_end = detected_start, detected_end
                except ValueError as e:
                    print(
                        f"  [{name}] [WARN] Auto-detection failed: {e} - proceeding with full window"
                    )

            interim_res = time_snapshots(
                table, window_size_s, max_time_s, active_start, active_end
            )

            if derived_metrics_enabled:
                interim_res = compute_derivatives(
                    interim_res,
                    smooth_window,
                    al_delta_p,
                    smooth_method,
                    butterworth_cutoff_hz,
                    butterworth_order,
                    complementary_alpha,
                    bessel_cutoff_hz,
                    bessel_order,
                    hampel_threshold,
                    wavelet_name,
                    wavelet_level,
                    wavelet_threshold_mode,
                    tv_weight,
                    loess_frac,
                    kalman_process_noise,
                    kalman_measurement_noise,
                )
                if smooth_method == "butterworth":
                    method_note = (
                        f", cutoff={butterworth_cutoff_hz}Hz, order={butterworth_order}"
                    )
                elif smooth_method == "bessel":
                    method_note = f", cutoff={bessel_cutoff_hz}Hz, order={bessel_order}"
                elif smooth_method == "complementary":
                    method_note = f", alpha={complementary_alpha}"
                elif smooth_method == "hampel":
                    method_note = f", threshold={hampel_threshold} sigma"
                elif smooth_method == "wavelet":
                    method_note = (
                        f", wavelet={wavelet_name}, mode={wavelet_threshold_mode}"
                    )
                elif smooth_method == "tv":
                    method_note = f", weight={tv_weight}"
                elif smooth_method == "loess":
                    method_note = f", frac={loess_frac}"
                elif smooth_method == "kalman":
                    method_note = (
                        f", Q={kalman_process_noise}, R={kalman_measurement_noise}"
                    )
                else:
                    method_note = ""
                print(
                    f"  [{name}] [OK] Derived metrics added (method={smooth_method}"
                    f"{method_note}, smooth_window={smooth_window}, delta_p={al_delta_p}): "
                    f"Setpoint, Pressure_filt, Contraction_filt, "
                    f"Velocity_Contraction, Velocity_Pressure, Acceleration_Contraction"
                )

            n_windows = int(interim_res["Cycle"].max()) if not interim_res.empty else 0
            sub_desc = (
                f" [{active_start or 0:.1f}-{active_end or window_size_s:.1f}s per window]"
                if (active_start or active_end)
                else ""
            )
            print(
                f"  [{name}] Time-based mode: {n_windows} window(s) of {window_size_s}s{sub_desc}"
            )
            feedstock = (
                interim_res
                if skip_active
                else cycle_active_loop(
                    interim_res,
                    al_active_len,
                    al_delta_p,
                    al_backup_time,
                    start_cycle=1,
                    end_cycle=n_windows,
                )
            )

            if new_metrics_enabled:
                _user_extra = compute_user_metrics(
                    feedstock, nm_config, full_df=interim_res
                )
                print(
                    f"  [{name}] [OK] User metrics added: {', '.join(_user_extra.keys()) or '(none)'}"
                )

        else:
            interim_res = cycle_snapshots(table, step_count, firstcyc, lastcyc)
            if skip_active:
                feedstock = interim_res
                print(f"  [{name}] Skipping cycle_active_loop (config override)")
            else:
                feedstock = cycle_active_loop(
                    interim_res,
                    al_active_len,
                    al_delta_p,
                    al_backup_time,
                    firstcyc,
                    lastcyc,
                )

        result = {
            "FullDat": interim_res,
            "activeDat": feedstock,
            "_source": source_meta,
            "_metadata": meta,
            "_metadata_file": str(found_metadata_path) if found_metadata_path else None,
        }
        if _user_extra:
            result.update(_user_extra)

        respoly, sumpoly, normpoly = combined_polyarea_normalization(
            feedstock, step_analysis
        )
        result["LoopArea_results"] = respoly
        result["LoopArea_summary"] = sumpoly
        result["LoopArea_norman"] = normpoly

        loop_mean = float(sumpoly["LoopArea_mean"].iloc[0])
        com_den = float(normpoly["comDen"].iloc[0])
        result["NormLoopValue"] = (
            loop_mean / com_den
            if not (np.isnan(loop_mean) or np.isnan(com_den) or com_den == 0)
            else np.nan
        )
        result["LoopMean"] = loop_mean
        result["LoopSTD"] = float(sumpoly["LoopArea_std"].iloc[0])

        res_initial_d, sum_initial_d, outlier_initial_d = centroid_drift_sum(
            feedstock, step_analysis
        )
        result["CentroidDrift_results"] = res_initial_d
        result["CentroidDrift_summary"] = sum_initial_d
        result["CentroidDrift_outlier"] = outlier_initial_d
        result["ellipse_result"] = ellipse_metric_for_centroid(res_initial_d)

        for _col in ("Centroid_Pressure", "Centroid_Pot"):
            if res_initial_d[_col].dtype == object:
                raise ValueError(
                    f"{_col} is non-numeric (object dtype) - CSV likely contains malformed rows"
                )
        cx = res_initial_d["Centroid_Pressure"].values.astype(float)
        cy = res_initial_d["Centroid_Pot"].values.astype(float)
        valid = ~(np.isnan(cx) | np.isnan(cy))
        if valid.sum() > 1:
            model = LinearRegression()
            model.fit(cx[valid].reshape(-1, 1), cy[valid])
            result["mdl_fit"] = model
            result["sigma_resid"] = float(
                np.std(cy[valid] - model.predict(cx[valid].reshape(-1, 1)), ddof=1)
            )
        else:
            result["mdl_fit"] = None
            result["sigma_resid"] = np.nan

        print("-" * 60)
        print(f"Analyzing: {source_meta}")
        print(f"Dataset name: {name}")
        cyc_res = cyc2cyc_corr_all(feedstock, npts, min_overlap)
        result["cyc2cyc_results"] = cyc_res
        result["dip_results"] = hartigans_dip_analysis(cyc_res, 500, 0.05)
        result["avgHystLoopTraj"] = avg_hyst_loop(feedstock, 601)

        ellipse_area = float(
            (result.get("ellipse_result") or {}).get("area", float("nan"))
        )
        nan_metrics = [
            k
            for k in ("LoopMean", "LoopSTD", "NormLoopValue")
            if np.isnan(float(result.get(k, float("nan"))))
        ]
        if np.isnan(ellipse_area):
            nan_metrics.append("ellipse_result.area")
        if nan_metrics:
            print(
                f"  [WARN] Warning {name} ({source_meta}): NaN in {', '.join(nan_metrics)} - likely bad DAQ data"
            )
            warnings_out.append(
                {
                    "dataset": name,
                    "source": str(source_meta),
                    "nan_metrics": nan_metrics,
                }
            )

        return name, result, None, warnings_out

    except Exception as exc:
        print(f"  [WARN] Skipping {name} ({source_meta}): {type(exc).__name__}: {exc}")
        return (
            name,
            None,
            {
                "dataset": name,
                "source": str(source_meta),
                "error": f"{type(exc).__name__}: {exc}",
            },
            [],
        )


def pam_metric_analysis_combined(
    data_source: str | Path,
    step_count: int = 1,
    step_analysis: int = 1,
    firstcyc: int = 1,
    lastcyc: int = 120,
    active_len: float = 6.0,
    delta_p: float = 3.44738,
    backup_time: float = 0.5,
    npts: int = 200,
    min_overlap: float = 0.90,
    n_workers: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Run the full PAM metric pipeline on a CSV folder. Returns a nested results dict.

    n_workers=None uses all CPU cores; set to 1 to force single-threaded for debugging.

    Author's Notes: Most of the configs can be swapped, but are legacy from back when
    cycle based modulo was used, today it primarily uses time instead.
    """
    tables, source_metadata, folder_paths = _load_data_files(data_source)
    _rename = {"Pressure_psi": "Pressure", "Pot_percent": "Contraction"}
    tables = {k: v.rename(columns=_rename) for k, v in tables.items()}

    work_items = [
        (
            name,
            table,
            source_metadata.get(name, "Unknown"),
            folder_paths.get(name),
            step_count,
            step_analysis,
            firstcyc,
            lastcyc,
            active_len,
            delta_p,
            backup_time,
            npts,
            min_overlap,
        )
        for name, table in tables.items()
    ]

    effective_workers = min(n_workers or os.cpu_count() or 1, len(work_items))

    if effective_workers <= 1 or len(work_items) <= 1:
        raw_results = [_process_one_dataset(item) for item in work_items]
    else:
        print(
            f"  Parallel processing: {len(work_items)} datasets across {effective_workers} workers"
        )
        try:
            with ProcessPoolExecutor(max_workers=effective_workers) as executor:
                raw_results = list(executor.map(_process_one_dataset, work_items))
        except BrokenProcessPool:
            # A worker was killed mid-run. On a small-RAM machine this is the OS
            # out-of-memory killer: every worker holds its own copy of a dataset
            # plus its results. Redo the whole run in this process, which is
            # slower but needs a fraction of the memory.
            print("[WARN] A worker process was killed (most likely out of memory).")
            print(
                "       Falling back to single-process mode - slower, but it will finish."
            )
            print("       To choose a middle ground, re-run with e.g. --workers 4.")
            raw_results = [_process_one_dataset(item) for item in work_items]

    io_results: dict = {}
    failures: list = []
    warnings_list: list = []
    for name, result, failure, warns in raw_results:
        if failure is not None:
            failures.append(failure)
        else:
            io_results[name] = result
            warnings_list.extend(warns)

    io_results["_failures"] = failures
    io_results["_warnings"] = warnings_list
    return io_results

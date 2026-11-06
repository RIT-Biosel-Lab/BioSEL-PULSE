"""run_analysis.py - Process csv data and store results in a singular file

Calls the following files: pam_metric_analysis.py, compute_derived_metrics.py, and user_metrics.py

One-time pipeline to analyze all datasets from csv and save:
  1. all_results.pkl  - Full reproducible results (metrics, models, data)
  2. summary.csv      - Summary table for papers
  3. summary.xlsx     - Formatted for reports
  4. log_output.md    - Auto-generated PKL field guide (keys, shapes, access snippets)
  5. log.md           - Failures/warnings (only written if something went wrong)

-- Author's Notes --
Author's Notes: This is meant to be the destination where hundreds of CSV can be processed
or loaded into a singular pkl file all in one place.

Note #2: Note that the pkl still preserves the original Nx4 data of the CSV, so this can
still be called as needed.

Note #3, August 31 2026: There is upcoming papers forthcoming that will build off this.
Current members of the BioSEL group + lead author will be collaborating to ensure compatibility.
"""

import sys
import argparse
import time
import pickle
import datetime
import numpy as np
import os
import pandas as pd
import psutil
from pathlib import Path

# Import the sibling modules in core/ whether this script is launched from inside
# core/, from Code/BioSEL-PULSE/, or from the root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pam_metric_analysis import (  # noqa: E402
    pam_metric_analysis_combined,
    combined_polyarea_normalization,
    centroid_drift_sum,
    ellipse_metric_for_centroid,
    configure_console,
)


# PKL field-guide generator


def _ascii_tree(sources: list[str], meta_folders: set[str]) -> list[str]:
    """Build an ASCII directory tree from slash-delimited source path strings.

    meta_folders: set of relative folder paths (e.g. "FolderA/Sub") that
    contain a .metadata.yaml so they can be annotated in the tree.
    """
    root: dict = {}
    for s in sorted(sources):
        if ":" in s:
            parts = s.split(":", 1)
        else:
            parts = s.split("/")
        node = root
        for part in parts:
            node = node.setdefault(part, {})

    out: list[str] = []

    def render(node: dict, prefix: str = "", path_so_far: str = "") -> None:
        children = sorted(node.keys())
        for idx, child in enumerate(children):
            is_last = idx == len(children) - 1
            conn = "└── " if is_last else "├── "
            child_prefix = prefix + ("    " if is_last else "│   ")
            is_leaf = not node[child]
            rel = f"{path_so_far}/{child}".strip("/") if path_so_far else child

            annotation = ""
            if not is_leaf and rel in meta_folders:
                annotation = "  <-- .metadata.yaml"

            label = child if is_leaf else f"{child}/"
            out.append(f"{prefix}{conn}{label}{annotation}\n")
            if node[child]:
                render(node[child], child_prefix, rel)

    render(root)
    return out


# Human-readable description for every key pam_metric_analysis_combined produces.
_KEY_DOCS = {
    "FullDat": (
        "Full time-windowed DataFrame before active-loop filtering. "
        "Use this when you need the complete pressurization + depressurization signal."
    ),
    "activeDat": (
        "Active-pressurization window - the primary analysis DataFrame. "
        "All core metrics (loop area, centroid, correlation) are computed from this. "
        "Any columns added by `derived_metrics` or `user_metrics.py` appear here."
    ),
    "_source": "Source path string showing the folder hierarchy of the dataset.",
    "LoopArea_results": (
        "Per-cycle hysteresis loop areas and cycle extrema "
        "(PeakPressure, RestingX, PeakX)."
    ),
    # Start of the BioSEL Research and metrics based on Thesis works
    "LoopArea_summary": "Summary stats (mean, std, min, max, median) of loop areas across cycles.",
    "LoopArea_norman": (
        "Normalization denominators: PressureNormalizeDelta, xNormalizeDelta, comDen. "
        "comDen is the divisor used to compute NormLoopValue."
    ),
    "LoopMean": "Mean hysteresis loop area across all cycles (scalar float).",
    "LoopSTD": "Standard deviation of hysteresis loop area across all cycles (scalar float).",
    "NormLoopValue": "LoopMean / comDen - dimensionless normalized loop metric (scalar float).",
    "CentroidDrift_results": (
        "Per-cycle centroid coordinates: Centroid_Pressure and Centroid_Pot. "
        "Mahalanobis outlier cycles are interpolated before storage."
    ),
    "CentroidDrift_summary": (
        "List of two stat dicts - index 0 = Pressure axis, index 1 = Pot axis. "
        "Each dict has keys: mean, std, min, max, median."
    ),
    "CentroidDrift_outlier": "Integer indices of cycles flagged as Mahalanobis outliers.",
    "ellipse_result": (
        "95% confidence ellipse fit to the centroid cloud. "
        "Keys: area, mu, axes, eccentricity, ellipse_coords, eigVec, eigVal."
    ),
    "mdl_fit": (
        "scikit-learn LinearRegression fit to the centroid trajectory "
        "(Centroid_Pressure -> Centroid_Pot). None if fewer than 2 valid points."
    ),
    "sigma_resid": "Residual std dev from the centroid linear fit (scalar float).",
    "cyc2cyc_results": "Cycle-to-cycle Pearson correlation in 3 domains: Input-Time, Output-Time, Hysteresis.",
    "dip_results": "Hartigan's dip test results on each correlation distribution (unimodality test).",
    "avgHystLoopTraj": "Mean and std of pressure/contraction trajectories resampled across cycles.",
}


def _write_log_output(io_results: dict, data_source: Path, results_dir: Path) -> None:
    """Write log_output.md - auto-generated field guide introspected from the first dataset in io_results."""
    real_datasets = [k for k in io_results if not k.startswith("_")]
    if not real_datasets:
        return

    rep_name = real_datasets[0]
    rep = io_results[rep_name]

    md = []

    # -- Header
    md.append("# PKL Output Reference\n\n")
    md.append(
        f"> Auto-generated by `run_analysis.py` on "
        f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n"
    )
    md.append(f"> Data source: `{data_source}`  \n")
    md.append(f"> Datasets in this run: **{len(real_datasets)}**  \n")
    md.append(f"> Representative dataset used below: `{rep_name}`  \n\n")
    md.append("---\n\n")

    # -- Quick-start
    md.append("## Quick Start\n\n")
    md.append("```python\n")
    md.append("import pickle\n\n")
    md.append('results = pickle.load(open("analysis_results/all_results.pkl", "rb"))\n')
    md.append('datasets = [k for k in results if not k.startswith("_")]\n\n')
    md.append("# Access one dataset\n")
    md.append(f'ds = results["{rep_name}"]\n\n')
    md.append("# The two core DataFrames\n")
    md.append('full_df   = ds["FullDat"]    # complete signal\n')
    md.append('active_df = ds["activeDat"]  # pressurized window only (primary)\n\n')
    md.append("# Key scalar metrics\n")
    md.append('ds["LoopMean"]      # mean hysteresis loop area\n')
    md.append('ds["NormLoopValue"] # normalized loop metric\n')
    md.append('ds["ellipse_result"]["area"]        # centroid ellipse area\n')
    md.append('ds["ellipse_result"]["eccentricity"] # centroid ellipse eccentricity\n')
    md.append("```\n\n")
    md.append("---\n\n")

    # -- Dataset list
    md.append("## Datasets in This Run\n\n")
    md.append("| Dataset | Source |\n")
    md.append("|---------|--------|\n")
    for ds in real_datasets:
        src = io_results[ds].get("_source", "Unknown")
        md.append(f"| `{ds}` | `{src}` |\n")
    md.append("\n---\n\n")

    # -- Key reference
    md.append("## Full Key Reference\n\n")
    md.append(
        f"Every dataset dict contains the keys below "
        f"(introspected from `{rep_name}`).\n\n"
    )

    for key, val in rep.items():
        if key == "_source":
            continue

        doc = _KEY_DOCS.get(key, "")
        md.append(f"### `{key}`\n\n")
        if doc:
            md.append(f"{doc}\n\n")

        try:
            from sklearn.linear_model import LinearRegression as _LR

            is_lr = isinstance(val, _LR)
        except ImportError:
            is_lr = False

        if isinstance(val, pd.DataFrame):
            rows, cols = val.shape
            col_list = ", ".join(f"`{c}`" for c in val.columns)
            md.append(f"**Type:** `DataFrame` - {rows} rows × {cols} cols  \n")
            md.append(f"**Columns:** {col_list}  \n\n")
            md.append("| Column | dtype | Example |\n")
            md.append("|--------|-------|---------|\n")
            for col in val.columns:
                col_dtype = str(val[col].dtype)
                non_nan = val[col].dropna()
                if non_nan.empty:
                    col_sample = "NaN"
                elif pd.api.types.is_float_dtype(val[col]):
                    col_sample = f"`{non_nan.iloc[0]:.4g}`"
                else:
                    col_sample = f"`{non_nan.iloc[0]}`"
                md.append(f"| `{col}` | `{col_dtype}` | {col_sample} |\n")
            md.append("\n")
            md.append("```python\n")
            md.append(f'df = results["YourDataset"]["{key}"]\n')
            if val.columns.tolist():
                md.append(f'df["{val.columns[0]}"]  # example column\n')
            md.append("```\n\n")

        elif isinstance(val, dict):
            subkeys = ", ".join(f"`{k}`" for k in val.keys())
            md.append(f"**Type:** `dict`  \n")
            md.append(f"**Keys:** {subkeys}  \n\n")
            md.append("```python\n")
            md.append(f'd = results["YourDataset"]["{key}"]\n')
            for k, v in list(val.items())[:4]:
                type_hint = type(v).__name__
                if isinstance(v, np.ndarray):
                    type_hint = f"ndarray shape={v.shape}"
                md.append(f'd["{k}"]  # {type_hint}\n')
            md.append("```\n\n")

        elif isinstance(val, list):
            md.append(f"**Type:** `list` ({len(val)} items)  \n")
            if val and isinstance(val[0], dict):
                item_keys = ", ".join(f"`{k}`" for k in val[0].keys())
                md.append(f"Each item is a `dict` with keys: {item_keys}  \n")
            md.append("\n```python\n")
            md.append(f'items = results["YourDataset"]["{key}"]\n')
            md.append(f"items[0]  # first item\n")
            if val and isinstance(val[0], dict):
                first_k = next(iter(val[0]))
                md.append(f'items[0]["{first_k}"]  # example sub-key\n')
            md.append("```\n\n")

        elif isinstance(val, np.ndarray):
            md.append(
                f"**Type:** `ndarray` - shape `{val.shape}`, dtype `{val.dtype}`  \n\n"
            )
            md.append("```python\n")
            md.append(f'arr = results["YourDataset"]["{key}"]\n')
            md.append("```\n\n")

        elif isinstance(val, float):
            md.append(f"**Type:** `float`  \n\n")
            md.append("```python\n")
            md.append(f'value = results["YourDataset"]["{key}"]  # e.g. {val:.6g}\n')
            md.append("```\n\n")

        elif is_lr:
            md.append(f"**Type:** `LinearRegression` (scikit-learn)  \n\n")
            md.append("```python\n")
            md.append(f'model = results["YourDataset"]["{key}"]\n')
            md.append("model.coef_       # slope(s)\n")
            md.append("model.intercept_  # intercept\n")
            md.append("model.predict([[x]])  # predict Pot from Pressure\n")
            md.append("```\n\n")

        elif val is None:
            md.append(
                "**Type:** `None` - insufficient centroid data for a linear fit.  \n\n"
            )

        else:
            md.append(f"**Type:** `{type(val).__name__}`  \n\n")
            md.append("```python\n")
            md.append(f'value = results["YourDataset"]["{key}"]\n')
            md.append("```\n\n")

    # -- activeDat column table
    active = rep.get("activeDat")
    if isinstance(active, pd.DataFrame) and not active.empty:
        md.append("---\n\n")
        md.append("## `activeDat` Column Reference\n\n")
        md.append(
            f"Shape for `{rep_name}`: "
            f"`{active.shape[0]} rows × {active.shape[1]} cols`  \n\n"
        )
        md.append("| Column | dtype | Example value | Notes |\n")
        md.append("|--------|-------|---------------|-------|\n")

        _col_notes = {
            "Time_s": "Elapsed time in seconds",
            "Pressure": "Pressure (units depend on conversion config)",
            "Contraction": "Contraction / potentiometer reading (legacy: Pot_percent in raw CSV)",
            "Cycle": "1-based time-window index",
            "Setpoint": "0/1 step input (derived_metrics only)",
            "Pressure_filt": "Filtered Pressure - same smoothing method as derivatives (derived_metrics only)",
            "Contraction_filt": "Filtered Contraction - same smoothing method as derivatives (derived_metrics only)",
            "Velocity_Contraction": "dPot/dt (derived_metrics only)",
            "Acceleration_Contraction": "d²Pot/dt² (derived_metrics only)",
            "Velocity_Pressure": "dPressure/dt (derived_metrics only)",
        }

        for col in active.columns:
            dtype = str(active[col].dtype)
            non_nan = active[col].dropna()
            if non_nan.empty:
                sample_str = "NaN"
            elif pd.api.types.is_float_dtype(active[col]):
                sample_str = f"`{non_nan.iloc[0]:.4g}`"
            else:
                sample_str = f"`{non_nan.iloc[0]}`"
            note = _col_notes.get(
                col, "user_metrics.py column" if col not in _col_notes else ""
            )
            md.append(f"| `{col}` | `{dtype}` | {sample_str} | {note} |\n")

        md.append("\n")

    # -- Section: Folder tree
    md.append("---\n\n")
    md.append("## Data Folder Tree\n\n")
    md.append(f"`{data_source.name}/`\n")
    md.append("```\n")

    # Collect which relative folders contain a .metadata.yaml
    meta_folders: set[str] = set()
    for ds in real_datasets:
        mf = io_results[ds].get("_metadata_file")
        if mf:
            try:
                rel_yaml = Path(mf).relative_to(data_source)
                # parent of the yaml file (e.g. "FolderA/SubB" for "FolderA/SubB/.metadata.yaml")
                folder_rel = str(rel_yaml.parent).replace("\\", "/")
                if folder_rel != ".":
                    meta_folders.add(folder_rel)
                else:
                    meta_folders.add("")  # root-level yaml
            except ValueError:
                pass

    sources = [io_results[ds].get("_source", ds) for ds in real_datasets]
    tree_lines = _ascii_tree(sources, meta_folders)
    md.extend(tree_lines)
    md.append("```\n\n")
    if meta_folders:
        md.append(
            "_Folders marked `<-- .metadata.yaml` have a config that was applied "
            "(see Metadata section below). Unmarked folders inherited from a parent "
            "or used pipeline defaults._\n\n"
        )

    # -- Section: Metadata applied per folder
    md.append("---\n\n")
    md.append("## Metadata Configuration Applied\n\n")

    # Group datasets by the yaml file that was applied to them
    # key: absolute yaml path (or None), value: list of dataset names
    yaml_groups: dict[str | None, list[str]] = {}
    for ds in real_datasets:
        mf = io_results[ds].get("_metadata_file")  # None if no yaml found
        yaml_groups.setdefault(mf, []).append(ds)

    # Datasets with no yaml, report briefly first
    no_yaml = yaml_groups.pop(None, [])
    if no_yaml:
        md.append("### No `.metadata.yaml` found\n\n")
        md.append(
            "These datasets used pipeline defaults "
            "(no unit conversions, `analysis_mode: cycle`).  \n"
        )
        for ds in sorted(no_yaml):
            src = io_results[ds].get("_source", ds)
            md.append(f"- `{ds}` - `{src}`\n")
        md.append("\n")

    # One section per unique yaml file
    for yaml_path, ds_list in sorted(yaml_groups.items()):
        yaml_abs = Path(yaml_path)

        # Relative display path (trim data_source root if possible)
        try:
            yaml_rel = yaml_abs.relative_to(data_source)
        except ValueError:
            yaml_rel = yaml_abs  # outside data_source, show as-is

        md.append(f"### `{yaml_rel}`\n\n")

        # Classify each dataset as direct (yaml is in its own folder) or inherited
        direct = []
        inherited = []
        for ds in sorted(ds_list):
            src = io_results[ds].get("_source", ds)
            # The dataset's folder is everything except the last path component
            ds_folder = "/".join(src.split("/")[:-1]) if "/" in src else ""
            yaml_folder = str(yaml_rel.parent).replace("\\", "/")
            if yaml_folder in (".", ""):
                yaml_folder = ""
            if ds_folder == yaml_folder:
                direct.append((ds, src))
            else:
                inherited.append((ds, src, ds_folder))

        if direct:
            md.append(f"**Direct** (yaml lives in the same folder as the CSV):  \n")
            for ds, src in direct:
                md.append(f"- `{ds}` - `{src}`\n")
            md.append("\n")

        if inherited:
            md.append(
                f"**Inherited** (yaml found by walking up from the CSV's folder):  \n"
            )
            for ds, src, ds_folder in inherited:
                folder_display = ds_folder if ds_folder else "(root)"
                md.append(f"- `{ds}` - `{src}` _(from `{folder_display}/`)_\n")
            md.append("\n")

        # Dump the actual yaml content
        md.append("**Config applied:**\n\n")
        md.append("```yaml\n")
        try:
            with open(yaml_abs, "r", encoding="utf-8") as f:
                raw_yaml = f.read()
            md.append(raw_yaml if raw_yaml.endswith("\n") else raw_yaml + "\n")
        except Exception as e:
            md.append(f"# Could not read file: {e}\n")
        md.append("```\n\n")

    # -- Column access quick reference
    active = rep.get("activeDat")
    if isinstance(active, pd.DataFrame) and not active.empty:
        md.append("---\n\n")
        md.append("## Column Access Quick Reference\n\n")
        md.append(
            f"Copy-paste access for every column in `FullDat` / `activeDat` "
            f"(same schema, introspected from `{rep_name}`).\n\n"
        )
        md.append("```python\n")
        md.append(f'ds = results["{rep_name}"]\n')
        md.append('active_df = ds["activeDat"]\n')
        md.append('full_df   = ds["FullDat"]\n\n')
        for col in active.columns:
            md.append(f'active_df["{col}"]\n')
        md.append("```\n\n")

    # -- User metrics section
    _core_keys = {
        "FullDat",
        "activeDat",
        "_source",
        "_metadata",
        "_metadata_file",
        "LoopArea_results",
        "LoopArea_summary",
        "LoopArea_norman",
        "NormLoopValue",
        "LoopMean",
        "LoopSTD",
        "CentroidDrift_results",
        "CentroidDrift_summary",
        "CentroidDrift_outlier",
        "ellipse_result",
        "mdl_fit",
        "sigma_resid",
        "cyc2cyc_results",
        "dip_results",
        "avgHystLoopTraj",
    }
    user_keys = [k for k in rep if k not in _core_keys]
    if user_keys:
        md.append("---\n\n")
        md.append("## User Metrics (`user_metrics.py`)\n\n")
        md.append(
            f"Keys added by `compute_user_metrics` "
            f"(introspected from `{rep_name}`).\n\n"
        )
        base_cols = set(rep.get("activeDat", pd.DataFrame()).columns)
        md.append("```python\n")
        md.append(f'ds = results["YourDataset"]\n\n')
        for key in user_keys:
            val = rep[key]
            if isinstance(val, pd.DataFrame):
                new_cols = [c for c in val.columns if c not in base_cols]
                for col in new_cols:
                    md.append(f'ds["{key}"]["{col}"]\n')
            else:
                md.append(f'ds["{key}"]\n')
            md.append("\n")
        md.append("```\n\n")

    # -- Write file
    log_path = results_dir / "log_output.md"
    with open(log_path, "w", encoding="utf-8") as f:
        f.writelines(md)
    print(f"   [OK] log_output.md (PKL field guide)")


def _build_filt_summary(io_results: dict) -> "pd.DataFrame | None":
    """Re-run scalar metrics on Pressure_filt/Contraction_filt columns. Returns None if no dataset has derived_metrics."""
    rows = []
    for ds_name, data in io_results.items():
        active = data.get("activeDat")
        if not isinstance(active, pd.DataFrame) or active.empty:
            continue
        if (
            "Pressure_filt" not in active.columns
            or "Contraction_filt" not in active.columns
        ):
            continue

        # Build a minimal 3-column frame so renamed columns don't conflict with originals
        filt_df = active[["Pressure_filt", "Contraction_filt", "Cycle"]].rename(
            columns={"Pressure_filt": "Pressure", "Contraction_filt": "Contraction"}
        )

        _, sumpoly, normpoly = combined_polyarea_normalization(filt_df, step=1)
        res_drift, sum_drift, _ = centroid_drift_sum(filt_df, step=1)
        ellipse = ellipse_metric_for_centroid(res_drift)

        loop_mean = float(sumpoly["LoopArea_mean"].iloc[0])
        com_den = float(normpoly["comDen"].iloc[0])
        norm_loop = (
            loop_mean / com_den
            if not (np.isnan(loop_mean) or np.isnan(com_den) or com_den == 0)
            else np.nan
        )

        rows.append(
            {
                "Source": data.get("_source", "Unknown"),
                "Dataset": ds_name,
                "LoopMean": loop_mean,
                "LoopSTD": float(sumpoly["LoopArea_std"].iloc[0]),
                "NormLoopValue": norm_loop,
                "CentroidPressure_mean": sum_drift[0]["mean"],
                "CentroidPressure_std": sum_drift[0]["std"],
                "CentroidDisplacement_mean": sum_drift[1]["mean"],
                "CentroidDisplacement_std": sum_drift[1]["std"],
                "EllipseArea": ellipse["area"],
                "Eccentricity": ellipse["eccentricity"],
            }
        )

    return pd.DataFrame(rows) if rows else None


if __name__ == "__main__":
    configure_console()

    start_time = time.time()
    process = psutil.Process(os.getpid())
    start_mem = process.memory_info().rss / 1024**2

    parser = argparse.ArgumentParser(
        description="BioSEL PAM metric analysis pipeline",
        epilog="Example: uv run python Code/BioSEL-PULSE/core/run_analysis.py Curated_Data",
    )
    parser.add_argument(
        "data_source",
        help="Path to a folder containing CSV data files (searched recursively).",
    )
    parser.add_argument(
        "--output",
        metavar="DIRNAME",
        default=None,
        help="Output folder (default: analysis_results, created in the current directory)",
    )
    parser.add_argument(
        "--workers",
        metavar="N",
        type=int,
        default=None,
        help="Worker processes (default: one per CPU core). Use a smaller number, "
        "or 1, if the run is killed on a machine with limited RAM.",
    )
    args = parser.parse_args()

    data_source = Path(args.data_source)
    if not data_source.is_absolute():
        data_source = Path.cwd() / data_source

    data_source = data_source.resolve()

    if not data_source.exists():
        print(f"[ERROR] {data_source} not found")
        print("        Pass the path to the data folder, e.g. Curated_Data")
        sys.exit(1)

    results_dir = (
        Path(args.output) if args.output else Path("analysis_results")
    ).resolve()
    results_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print(f"ANALYZING {data_source.name}")
    print(f"  data source: {data_source}")
    print(f"  results dir: {results_dir}")
    print("=" * 80)

    try:
        io_results = pam_metric_analysis_combined(
            data_source,
            step_count=1,  # Increment by a Cycle
            step_analysis=1,
            firstcyc=1,
            lastcyc=120,  # This is the max, I would use the config files to tailor it
            active_len=6,  # 6 seconds of snapshots,
            delta_p=3.44738,
            backup_time=0.5,
            npts=200,
            min_overlap=0.90,
            n_workers=args.workers,  # None = one worker per CPU core
        )
    except (ValueError, FileNotFoundError) as exc:
        # No CSVs, or none in the expected shape. Say so plainly instead of
        # leaving an empty analysis_results/ folder and a stack trace.
        print()
        print("=" * 80)
        print("[ERROR] Nothing was analyzed.")
        print("=" * 80)
        print(exc)
        sys.exit(1)

    # Extract failures and warnings, write log.md if either exist
    failures = io_results.pop("_failures", [])
    warnings_list = io_results.pop("_warnings", [])

    if not io_results:
        # Every dataset raised. Write the log so the reason is on disk, then stop:
        # continuing would only produce an empty PKL and an empty summary table.
        log_path = results_dir / "log.md"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# Analysis Log\n\n")
            f.write(f"Run: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Data source: {data_source}\n\n")
            f.write(f"## Failures ({len(failures)} datasets, all of them)\n\n")
            for f_entry in failures:
                f.write(f"### {f_entry['dataset']}\n")
                f.write(f"- **Source:** `{f_entry['source']}`\n")
                f.write(f"- **Error:** `{f_entry['error']}`\n\n")
        print()
        print("=" * 80)
        print(
            f"[ERROR] All {len(failures)} dataset(s) failed. No results were written."
        )
        print("=" * 80)
        for f_entry in failures[:5]:
            print(f"  {f_entry['dataset']}: {f_entry['error']}")
        if len(failures) > 5:
            print(f"  ... and {len(failures) - 5} more")
        print(f"\nFull list: {log_path}")
        sys.exit(1)
    if failures or warnings_list:
        log_lines = [
            f"# Analysis Log\n",
            f"Run: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            f"Data source: {data_source}\n\n",
        ]
        if failures:
            log_lines.append(f"## Failures ({len(failures)} skipped)\n\n")
            for f_entry in failures:
                log_lines.append(f"### {f_entry['dataset']}\n")
                log_lines.append(f"- **Source:** `{f_entry['source']}`\n")
                log_lines.append(f"- **Error:** `{f_entry['error']}`\n\n")
        if warnings_list:
            log_lines.append(
                f"## Warnings ({len(warnings_list)} included with NaN metrics)\n\n"
            )
            for w_entry in warnings_list:
                log_lines.append(f"### {w_entry['dataset']}\n")
                log_lines.append(f"- **Source:** `{w_entry['source']}`\n")
                log_lines.append(
                    f"- **NaN metrics:** `{', '.join(w_entry['nan_metrics'])}`\n\n"
                )
        log_path = results_dir / "log.md"
        with open(log_path, "w", encoding="utf-8") as f:
            f.writelines(log_lines)
        if failures:
            print(
                f"\n[WARN] {len(failures)} dataset(s) failed (excluded) - see {log_path}"
            )
        if warnings_list:
            print(
                f"[WARN] {len(warnings_list)} dataset(s) have NaN metrics (still included) - see {log_path}"
            )

    # Extract summary for paper table (grouped by source)
    summary_rows = []
    for ds_name, data in io_results.items():
        summary_rows.append(
            {
                "Source": data.get("_source", "Unknown"),
                "Dataset": ds_name,
                "LoopMean": data["LoopMean"],
                "LoopSTD": data["LoopSTD"],
                "NormLoopValue": data["NormLoopValue"],
                "CentroidPressure_mean": data["CentroidDrift_summary"][0]["mean"],
                "CentroidPressure_std": data["CentroidDrift_summary"][0]["std"],
                "CentroidDisplacement_mean": data["CentroidDrift_summary"][1]["mean"],
                "CentroidDisplacement_std": data["CentroidDrift_summary"][1]["std"],
                "EllipseArea": data["ellipse_result"]["area"],
                "Eccentricity": data["ellipse_result"]["eccentricity"],
            }
        )

    summary_df = pd.DataFrame(summary_rows)

    # Save results
    print("\n[SAVE] Saving results...")

    with open(results_dir / "all_results.pkl", "wb") as f:
        pickle.dump(io_results, f)
    print(f"   [OK] all_results.pkl (reproducible results)")

    with open(results_dir / "summary.csv", "w", encoding="utf-8", newline="") as f:
        sources = summary_df["Source"].unique()
        for source in sorted(sources):
            source_data = summary_df[summary_df["Source"] == source]
            f.write(f"{source}\n")
            f.write("\n")
            source_data.drop(columns=["Source"]).to_csv(f, index=False)
            f.write("=" * 80 + "\n")
    print(f"   [OK] summary.csv (grouped by source)")

    try:
        summary_df.to_excel(results_dir / "summary.xlsx", index=False)
        print(f"   [OK] summary.xlsx (formatted)")
    except ImportError:
        print(f"   [WARN] summary.xlsx skipped (install openpyxl for Excel export)")

    filt_summary_df = _build_filt_summary(io_results)
    if filt_summary_df is not None:
        with open(
            results_dir / "summary_filt.csv", "w", encoding="utf-8", newline=""
        ) as f:
            for source in sorted(filt_summary_df["Source"].unique()):
                source_data = filt_summary_df[filt_summary_df["Source"] == source]
                f.write(f"{source}\n\n")
                source_data.drop(columns=["Source"]).to_csv(f, index=False)
                f.write("=" * 80 + "\n")
        print(
            f"   [OK] summary_filt.csv (filtered signals - Pressure_filt / Contraction_filt)"
        )
        try:
            filt_summary_df.to_excel(results_dir / "summary_filt.xlsx", index=False)
            print(f"   [OK] summary_filt.xlsx (formatted)")
        except ImportError:
            pass
    else:
        print(
            f"   [INFO] summary_filt.csv skipped - no datasets with derived_metrics enabled"
        )

    _write_log_output(io_results, data_source, results_dir)

    print("\n" + "=" * 80)
    print("ANALYSIS SUMMARY")
    print("=" * 80)
    print(f"Datasets analyzed: {len(summary_df)}")
    print("\nSource hierarchy:")
    for source in summary_df["Source"].unique():
        count = len(summary_df[summary_df["Source"] == source])
        print(f"  {source}: {count} dataset(s)")

    print("\n" + "-" * 80)
    print("METRICS TABLE")
    print("-" * 80)
    print(summary_df.to_string(index=False))

    print("\n" + "=" * 80)
    print(f"[OK] Analysis complete. Results in {results_dir}/")
    print("=" * 80)

    elapsed = time.time() - start_time
    end_mem = process.memory_info().rss / 1024**2
    cpu_percent = process.cpu_percent(interval=0.1)

    print("\n" + "=" * 80)
    print("PERFORMANCE SUMMARY")
    print("=" * 80)
    print(f"[TIME]  Elapsed time:  {elapsed:.2f}s ({elapsed / 60:.1f}m)")
    print(
        f"[SAVE] Memory used:   {start_mem:.1f}MB -> {end_mem:.1f}MB (delta {end_mem - start_mem:+.1f}MB)"
    )
    print(f"[CPU] CPU usage:     {cpu_percent:.1f}%")
    print("=" * 80)

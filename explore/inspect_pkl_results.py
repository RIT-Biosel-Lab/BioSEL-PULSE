"""inspect_pkl_results.py - View pkl results in terminal.

Shows analysis metrics from all_results.pkl for one dataset.

Usage:
    uv run python explore/inspect_pkl_results.py                   # interactive: pick from list
    uv run python explore/inspect_pkl_results.py dataset_name      # show a specific dataset
    uv run python explore/inspect_pkl_results.py --input <folder>  # read a specific results folder

Author's Note: This is in my opinion, my favorite tools for me to use when iterating. I suggest using this if you just want
peer upon the visage of pure metrics in the glory of the terminal.
"""

import argparse
import pickle
import sys
from pathlib import Path

_DEFAULT_DIR = Path(
    "analysis_results"
)  # cwd-relative, matches run_analysis.py's default output


def _resolve_results_dir(requested: str | None) -> Path:
    if requested is None:
        return _DEFAULT_DIR

    req = Path(requested)
    if not req.is_absolute():
        req = Path.cwd() / req

    if (req / "all_results.pkl").exists():
        return req

    print(
        f"[WARN] '{requested}' not found or missing all_results.pkl - falling back to default '{_DEFAULT_DIR.name}'"
    )

    if not (_DEFAULT_DIR / "all_results.pkl").exists():
        print(
            f"[ERROR] Default folder '{_DEFAULT_DIR}' also has no all_results.pkl - nothing to show."
        )
        print("   Generate results:  uv run python core/run_analysis.py <path/to/data>")
        print(
            "   Or, if the pkl is elsewhere, point --input at the folder holding all_results.pkl."
        )
        sys.exit(1)

    return _DEFAULT_DIR


def load_results(results_dir: Path):
    pkl_path = results_dir / "all_results.pkl"
    if not pkl_path.exists():
        print(f"[ERROR] {pkl_path} not found")
        print("   Generate results:  uv run python core/run_analysis.py <path/to/data>")
        print(
            "   Or, if the pkl is elsewhere, point --input at the folder holding all_results.pkl."
        )
        sys.exit(1)
    with open(pkl_path, "rb") as f:
        return pickle.load(f)


def show_dataset(all_results, ds_name):
    """Display all metrics for a single dataset."""
    if ds_name not in all_results:
        print(f"[ERROR] Dataset '{ds_name}' not found")
        print(f"Available: {list(all_results.keys())}")
        return

    data = all_results[ds_name]

    print("\n" + "=" * 80)
    print(f"{ds_name}")
    print("=" * 80)

    print(f"\nSource: {data.get('_source', '?')}")

    # Loop metrics
    print("\nLoop Area:")
    print(f"  Mean:       {data.get('LoopMean', '?')}")
    print(f"  Std:        {data.get('LoopSTD', '?')}")
    print(f"  Normalized: {data.get('NormLoopValue', '?')}")

    if "LoopArea_summary" in data:
        s = data["LoopArea_summary"]
        print(f"  Min:        {s['LoopArea_min'].iloc[0]}")
        print(f"  Max:        {s['LoopArea_max'].iloc[0]}")
        print(f"  Median:     {s['LoopArea_median'].iloc[0]}")

    if "LoopArea_norman" in data:
        n = data["LoopArea_norman"]
        print(f"\nLoop Area Normalization:")
        for col in n.columns:
            val = n[col].iloc[0]
            print(f"  {col}: {val}")

    if "LoopArea_results" in data:
        df = data["LoopArea_results"]
        print(f"\nLoop Area Results:")
        print(df.head(5).to_string(index=False))
        if len(df) > 5:
            print(df.tail(5).to_string(index=False))

    # Centroid drift
    print("\nCentroid Drift:")
    if "CentroidDrift_summary" in data:
        p = data["CentroidDrift_summary"][0]
        d = data["CentroidDrift_summary"][1]
        print(f"  Pressure (mean+/-std):     {p['mean']:.4f} +/- {p['std']:.4f}")
        print(f"  Displacement (mean+/-std): {d['mean']:.4f} +/- {d['std']:.4f}")

    if "CentroidDrift_outlier" in data:
        outliers = data["CentroidDrift_outlier"]
        print(f"  Outliers:  {len(outliers)} cycles")

    if "CentroidDrift_results" in data:
        df = data["CentroidDrift_results"]
        print(f"\nCentroid Drift Results:")
        print(df.head(5).to_string(index=False))
        if len(df) > 5:
            print(df.tail(5).to_string(index=False))

    # Ellipse from centroid drift
    if "ellipse_result" in data:
        e = data["ellipse_result"]
        print(f"\nCentroid Drift Ellipse (95% confidence):")
        print(f"  Area:           {e.get('area', '?')}")
        print(f"  Eccentricity:   {e.get('eccentricity', '?')}")
        print(f"  Center:         {e.get('mu', '?')}")
        print(f"  Axes:           {e.get('axes', '?')}")

    # Linear regression trend from centroid drift
    if "mdl_fit" in data and data["mdl_fit"] is not None:
        m = data["mdl_fit"]
        print(f"\nCentroid Drift Trend (Linear Regression):")
        print(f"  Coefficient:  {m.coef_[0]:.6f}")
        print(f"  Intercept:    {m.intercept_:.6f}")
        print(f"  Residual std: {data.get('sigma_resid', '?')}")

    # Correlations
    print("\nCycle-to-Cycle Correlation:")
    if "cyc2cyc_results" in data:
        df = data["cyc2cyc_results"]
        for _, row in df.iterrows():
            domain = row["Domain"]
            mean = row["MeanCorr"]
            std = row["StdCorr"]
            valid = row["ValidPairs"]
            total = row["TotalPairs"]
            print(f"  {domain:15} {mean:.4f} +/- {std:.4f}  ({valid}/{total} pairs)")

    # Dip test
    print("\nHartigan's Dip Test (unimodality):")
    if "dip_results" in data:
        df = data["dip_results"]
        for _, row in df.iterrows():
            domain = row["Domain"]
            dip = row["DipStat"]
            pval = row["p_value"]
            sig = "YES" if row["Significant"] else "no"
            print(f"  {domain:15} dip={dip:.4f}, p={pval:.4f} (sig={sig})")

    # Data sizes
    print("\nData:")
    if "FullDat" in data:
        print(f"  FullDat rows:    {len(data['FullDat'])}")
    if "activeDat" in data:
        print(f"  activeDat rows:  {len(data['activeDat'])}")


def interactive_picker(all_results):
    """Let user pick a dataset from a numbered list and thus granting immortal decision paralysis."""
    names = sorted(all_results.keys())

    print(f"\n{len(names)} datasets found:\n")
    for i, name in enumerate(names, 1):
        loop_mean = all_results[name].get("LoopMean", "?")
        source = all_results[name].get("_source", "?")
        print(f"  {i:3d}. {name:30} loop_mean={loop_mean:10}")

    print("\nEnter dataset number or name (or 'q' to quit): ", end="")
    choice = input().strip()

    if choice.lower() == "q":
        return None

    # Try as number first
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(names):
            return names[idx]
    except ValueError:
        pass

    # Try as name
    if choice in names:
        return choice

    print(f"[ERROR] Not found: {choice}")
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Inspect PAM results from all_results.pkl"
    )
    parser.add_argument(
        "dataset",
        nargs="?",
        help="Dataset name to inspect (default: interactive picker)",
    )
    parser.add_argument(
        "--input",
        metavar="DIRNAME",
        default=None,
        help="Results folder to read from (default: analysis_results)",
    )
    args = parser.parse_args()

    results_dir = _resolve_results_dir(args.input)
    all_results = load_results(results_dir)

    if args.dataset:
        show_dataset(all_results, args.dataset)
    else:
        while True:
            ds_name = interactive_picker(all_results)
            if ds_name is None:
                print("\n Goodbye")
                break
            show_dataset(all_results, ds_name)
            print("\n" + "-" * 80)
            input("Press Enter to pick another dataset...")
            print("\n")


if __name__ == "__main__":
    main()

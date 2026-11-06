#!/usr/bin/env python3
"""Report sample and actuation-cycle counts from an all_results.pkl file."""
# Command: uv run python tools/count_samples.py analysis_results/all_results.pkl
import sys
import pickle
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print("Usage: python count_samples.py <path/to/all_results.pkl>")
        sys.exit(1)

    pkl_path = Path(sys.argv[1])

    if not pkl_path.exists():
        print(f"Error: '{pkl_path}' does not exist")
        sys.exit(1)

    if not pkl_path.is_file():
        print(f"Error: '{pkl_path}' is not a file")
        sys.exit(1)

    with open(pkl_path, "rb") as f:
        results = pickle.load(f)

    datasets = [k for k in results if not k.startswith("_")]

    if not datasets:
        print("No datasets found in PKL.")
        sys.exit(0)

    print(f"\nPKL: {pkl_path}  ({len(datasets)} dataset(s))\n")

    total_samples = 0
    total_cycles = 0
    max_name = max(len(d) for d in datasets)
    max_src = max(len(str(results[d].get("_source", ""))) for d in datasets)

    for ds_name in sorted(datasets):
        ds = results[ds_name]
        full_dat = ds.get("FullDat")
        source = ds.get("_source", "?")

        if full_dat is None or full_dat.empty:
            print(f"  {ds_name:<{max_name}}  [{source}]:  (no FullDat)")
            continue

        samples = len(full_dat)
        cycles = int(full_dat["Cycle"].nunique()) if "Cycle" in full_dat.columns else 0

        total_samples += samples
        total_cycles += cycles

        print(f"  {ds_name:<{max_name}}  [{source:<{max_src}}]:  {samples:>6} samples,  {cycles:>4} cycles")

    print(f"\n{'='*55}")
    print(f"Total samples: {total_samples}  |  Total cycles: {total_cycles}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()

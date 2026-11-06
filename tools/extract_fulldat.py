"""extract_fulldat.py: Extract raw NX4 from CSV into a single pkl with no metric computation if raw CSV
values in pkl format is all that is needed.

Loads each CSV exactly as the main pipeline does (header detection, encoding
fallback, .metadata.yaml unit conversions), renames columns to the canonical
form, and writes a single all_fulldat.pkl keyed by dataset name. This is a fork of the
run_analysis.py and was designed to provide end users with a pkl that gathers all csv and just
convert psi to kPa (must use the .metadata config for this), scale up the Potentiometer by 1.13
and preserve the whole thing for the provided data.

Each PKL entry is a DataFrame with columns: Time_s, Pressure, Contraction, Cycle

Usage:
    uv run python tools/extract_fulldat.py path/to/FolderA
    uv run python tools/extract_fulldat.py path/to/FolderA path/to/FolderB path/to/FolderC
    uv run python tools/extract_fulldat.py path/to/FolderA path/to/FolderB --output my_dir
Author's Note: This was added in just in case someone wanted just raw values, just copied and pasted from the original core/ and modified with aid of psuedocode + /plan of Claude (No data was fed in by author's operating procedures in line with BioSEL).
"""

import sys
import argparse
import pickle
import yaml
from pathlib import Path

import pandas as pd


_RENAME = {"Pressure_psi": "Pressure", "Pot_percent": "Contraction"}
_NEW_DAQ = {
    "Time(s)": "Time_s",
    "Pressure(psi)": "Pressure_psi",
    "Potentiometer(%)": "Pot_percent",
    "Cycle(-)": "Cycle",
}
_REQUIRED = {"Time_s", "Pressure_psi", "Pot_percent", "Cycle"}


def _find_header_row(filepath: Path) -> int:
    """Return 0-indexed line number where the CSV header starts, or -1 if not found."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                parts = [p.strip().strip('"').strip("'") for p in line.split(",")]
                normalized = {_NEW_DAQ.get(p, p) for p in parts}
                if _REQUIRED.issubset(normalized) or _REQUIRED.issubset(set(parts)):
                    return i
    except Exception:
        pass
    return -1


def _apply_metadata(df: pd.DataFrame, csv_path: Path) -> pd.DataFrame | None:
    """Walk up the folder tree to find .metadata.yaml and apply unit conversions."""
    current = csv_path.parent
    while current != current.parent:
        candidate = current / ".metadata.yaml"
        if candidate.exists():
            try:
                with open(candidate, "r", encoding="utf-8") as fh:
                    config = yaml.safe_load(fh)
                bypass = (config or {}).get("bypass", False)
                if isinstance(bypass, str):
                    bypass = bypass.strip().lower() == "true"
                if bypass:
                    return None  # signal: skip this file
                if config and config.get("processed") is False:
                    conv = config.get("conversions", {})
                    if conv.get("psi_to_kpa"):
                        df["Pressure_psi"] = df["Pressure_psi"] * 6.89476
                    if conv.get("pot_percent_scale_factor"):
                        df["Pot_percent"] = (
                            df["Pot_percent"] * conv["pot_percent_scale_factor"]
                        )
            except Exception as e:
                print(f"  Warning: could not read {candidate.name}: {e}")
            break
        current = current.parent
    return df


def _load_csv(csv_path: Path) -> pd.DataFrame | None:
    """Load one CSV and return a renamed NX4 DataFrame, or None on failure."""
    header_row = _find_header_row(csv_path)
    if header_row == -1:
        print(f"  Skipping {csv_path.name}: header not found")
        return None

    df = None
    for enc in ("utf-8", "latin-1", "cp1252", "iso-8859-1"):
        try:
            df = pd.read_csv(
                csv_path, encoding=enc, skiprows=header_row, low_memory=False
            )
            break
        except Exception:
            df = None

    if df is None:
        try:
            df = pd.read_csv(
                csv_path,
                encoding="utf-8",
                encoding_errors="replace",
                skiprows=header_row,
                low_memory=False,
            )
        except Exception as e:
            print(f"  Skipping {csv_path.name}: {e}")
            return None

    df = df.rename(columns=_NEW_DAQ)

    if not _REQUIRED.issubset(df.columns):
        print(f"  Skipping {csv_path.name}: missing required columns")
        return None

    if df.shape[1] != 4:
        print(f"  Skipping {csv_path.name}: expected 4 columns, got {df.shape[1]}")
        return None

    for col in ("Time_s", "Pressure_psi", "Pot_percent"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Cycle"] = pd.to_numeric(df["Cycle"], errors="coerce")

    df = _apply_metadata(df, csv_path)
    if df is None:
        print(f"  Skipping {csv_path.name}: bypass flag set in .metadata.yaml")
        return None

    return df.rename(columns=_RENAME)[["Time_s", "Pressure", "Contraction", "Cycle"]]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract NX4 FullDat into a single PKL.",
        epilog="Example: uv run python tools/extract_fulldat.py FolderA FolderB FolderC",
    )
    parser.add_argument(
        "data_sources",
        nargs="+",
        help="One or more folders containing CSV data files (searched recursively).",
    )
    parser.add_argument(
        "--output",
        metavar="DIR",
        default=None,
        help="Output folder (default: fulldat_output)",
    )
    args = parser.parse_args()

    out_dir = Path(args.output) if args.output else Path("fulldat_output")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Collect all CSV files across all input folders
    all_csv_files: list[tuple[Path, Path]] = []  # (csv_path, its data_source root)
    for src in args.data_sources:
        data_source = Path(src).resolve()
        if not data_source.exists() or not data_source.is_dir():
            print(f"Warning: {data_source} is not an existing directory - skipping")
            continue
        found = sorted(data_source.rglob("*.csv"))
        print(f"Found {len(found)} CSV file(s) in {data_source.name}/")
        all_csv_files.extend((csv_path, data_source) for csv_path in found)

    if not all_csv_files:
        print("No CSV files found in any of the provided folders.")
        sys.exit(1)

    results = {}
    failed = []

    for csv_path, data_source in all_csv_files:
        rel = csv_path.relative_to(data_source)
        dataset_name = f"{data_source.name}_{str(rel.with_suffix('').as_posix()).replace('/', '_')}"
        df = _load_csv(csv_path)
        if df is None:
            failed.append(str(csv_path))
            continue
        results[dataset_name] = df
        print(
            f"  Loaded {data_source.name}/{rel} -> '{dataset_name}' ({len(df):,} rows)"
        )

    if failed:
        print(f"\n[WARN] Could not load {len(failed)} file(s):")
        for f in failed:
            print(f"     {f}")

    if not results:
        print("No datasets loaded - nothing written.")
        sys.exit(1)

    out_path = out_dir / "all_fulldat.pkl"
    with open(out_path, "wb") as fh:
        pickle.dump(results, fh)

    print(f"\nWrote {len(results)} dataset(s) to {out_path}")


if __name__ == "__main__":
    main()

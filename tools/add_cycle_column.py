"""add_cycle_column.py - Promote Nx3 CSV files to Nx4 by adding a Cycle column.

For CSV folders that already have [Time_s, Pressure_psi, Pot_percent] but are
missing the Cycle column required by the analysis pipeline. Skips any file that
already has Cycle.

    Cycle = floor((Time_s - Time_s[0]) / cycle_duration) + 1   (1-based, integer)

Place a metadata.yaml in the data folder with the cycle duration, then run:

    python tools/add_cycle_column.py /path/to/data_folder            # -> _cycled/
    python tools/add_cycle_column.py /path/to/data_folder --out /p   # custom out
    python tools/add_cycle_column.py /path/to/data_folder --in-place # overwrite
    python tools/add_cycle_column.py /path/to/data_folder --dry-run  # preview

metadata.yaml (in the data folder)
------------------------------------
Minimal:
    cycle_duration: 20   # seconds per cycle

Or reuse existing pipeline metadata (time_window.window_size_seconds works too):
    time_window:
      window_size_seconds: 20
Author's Note: This really doesn't need to be developed, it was bolted together with Claude Haiku to gather Nx3 csv from the oldest batch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


REQUIRED_COLS = {"Time_s", "Pressure_psi", "Pot_percent"}
OUTPUT_COL_ORDER = ["Time_s", "Pressure_psi", "Pot_percent", "Cycle"]


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _load_metadata(folder: Path) -> dict:
    """Return parsed YAML from metadata.yaml or .metadata.yaml in folder."""
    for name in ("metadata.yaml", ".metadata.yaml"):
        p = folder / name
        if p.exists():
            with open(p, encoding="utf-8", errors="replace") as f:
                return yaml.safe_load(f) or {}
    return {}


def _get_cycle_duration(meta: dict) -> float | None:
    """Extract cycle_duration from metadata dict. Returns None if not found."""
    if "cycle_duration" in meta:
        return float(meta["cycle_duration"])
    try:
        return float(meta["time_window"]["window_size_seconds"])
    except (KeyError, TypeError):
        return None


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------


def _find_header_row(filepath: Path) -> int:
    """Return 0-indexed line number of the CSV header, skipping BioSEL metadata preamble."""
    for encoding in ("utf-8", "latin-1"):
        try:
            lines = filepath.read_text(encoding=encoding).splitlines()
            break
        except UnicodeDecodeError:
            continue
    else:
        return 0

    marker = "=== THIS IS THE START OF A NEW RUN ==="
    marker_idx = next(
        (i for i, ln in enumerate(lines) if marker.lower() in ln.lower()), None
    )

    if marker_idx is not None:
        for i in range(marker_idx + 1, len(lines)):
            ln = lines[i].strip()
            if not ln:
                continue
            if "humidity" in ln.lower() or "temperature" in ln.lower():
                continue
            return i
    else:
        for i, ln in enumerate(lines):
            if ln.strip().startswith("Time_s"):
                return i

    return 0


def _load_csv(filepath: Path) -> pd.DataFrame:
    header_row = _find_header_row(filepath)
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(
                filepath, skiprows=header_row, encoding=encoding, low_memory=False
            )
            for col in ("Time_s", "Pressure_psi", "Pot_percent"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            if "Cycle" in df.columns:
                df["Cycle"] = pd.to_numeric(df["Cycle"], errors="coerce")
            return df
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode {filepath}")


# ---------------------------------------------------------------------------
# Core transform
# ---------------------------------------------------------------------------


def add_cycle_column(df: pd.DataFrame, cycle_duration: float) -> pd.DataFrame:
    """Return copy of df with Cycle column stamped from time windows (1-based)."""
    df = df.copy()
    t = pd.to_numeric(df["Time_s"], errors="coerce")
    t_rel = t - t.min()
    df["Cycle"] = np.floor(t_rel / cycle_duration).astype("Int64") + 1
    return df


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------


def _process_file(
    src: Path,
    dst: Path,
    cycle_duration: float,
    dry_run: bool,
) -> bool:
    try:
        df = _load_csv(src)
    except Exception as exc:
        print(f"  SKIP  {src.name}: load error - {exc}")
        return False

    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        print(f"  SKIP  {src.name}: missing columns {missing}")
        return False

    if "Cycle" in df.columns:
        print(f"  SKIP  {src.name}: Cycle column already present")
        return False

    df = add_cycle_column(df, cycle_duration)
    df = df[OUTPUT_COL_ORDER]  # exactly Nx4, drop anything else

    max_cycle = int(df["Cycle"].max())
    print(f"  OK    {src.name}: {len(df)} rows -> {max_cycle} cycles")

    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(dst, index=False)

    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stamp a time-based Cycle column onto every CSV in a folder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "data_dir", type=Path, help="Folder containing CSVs and metadata.yaml"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="DIR",
        help="Output folder. Defaults to <data_dir>_cycled.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Write back to the same folder (overwrites originals).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without writing anything.",
    )

    args = parser.parse_args(argv)

    if args.in_place and args.out:
        parser.error("--in-place and --out are mutually exclusive.")

    data_dir: Path = args.data_dir.resolve()
    if not data_dir.is_dir():
        print(f"ERROR: {data_dir} is not a directory.")
        return 1

    # Load metadata and resolve cycle duration
    meta = _load_metadata(data_dir)
    cycle_duration = _get_cycle_duration(meta)

    if cycle_duration is None:
        print(
            f"ERROR: No cycle_duration found in metadata.yaml in {data_dir}\n\n"
            "Add one of these to metadata.yaml:\n"
            "  Minimal:     cycle_duration: 20\n"
            "  Pipeline:    time_window:\n"
            "                 window_size_seconds: 20"
        )
        return 1

    # Resolve output root
    if args.in_place:
        out_root = data_dir
    elif args.out:
        out_root = args.out.resolve()
    else:
        out_root = data_dir.parent / (data_dir.name + "_cycled")

    # Collect CSV files
    csv_files = sorted(data_dir.rglob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {data_dir}")
        return 1

    print(f"Data folder    : {data_dir}")
    print(f"Cycle duration : {cycle_duration}s")
    print(f"Output folder  : {out_root}")
    print(f"Files          : {len(csv_files)}")
    if args.dry_run:
        print("[dry-run] No files will be written.\n")
    else:
        print()

    pairs = [
        (csv_file, out_root / csv_file.relative_to(data_dir)) for csv_file in csv_files
    ]

    ok = sum(
        _process_file(src, dst, cycle_duration, args.dry_run) for src, dst in pairs
    )
    failed = len(pairs) - ok

    print(f"\nDone: {ok} succeeded, {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

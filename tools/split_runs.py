"""split_runs.py | Split multi-run CSV files into separate files if needed

Legacy CSVs sometimes contain multiple runs concatenated together, each
preceded by "=== THIS IS THE START OF A NEW RUN ===". This script detects
those markers and writes each run to its own file.

    example.csv          -> example.csv        (first run, trimmed in place)
                         -> example_split01.csv (second run)
                         -> example_split02.csv (third run, if present)

Single-run files are left untouched.

Configure via metadata.yaml in the data folder:
    separate_runs: true

Usage
-----
    python tools/split_runs.py /path/to/folder            # -> _split/ folder
    python tools/split_runs.py /path/to/folder --in-place # modify originals
    python tools/split_runs.py /path/to/folder --dry-run  # preview only

Author's Note: This python script is highly experimental and was largely only meant for the BioSEL
Original Data's raw superlative files. Since then, there hasn't been a strong use case for this but is
retained in case this is needed.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml

MARKER = "=== THIS IS THE START OF A NEW RUN ==="


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _load_metadata(folder: Path) -> dict:
    for name in ("metadata.yaml", ".metadata.yaml"):
        p = folder / name
        if p.exists():
            with open(p, encoding="utf-8", errors="replace") as f:
                return yaml.safe_load(f) or {}
    return {}


def _should_split(meta: dict) -> bool:
    val = meta.get("separate_runs", False)
    if isinstance(val, str):
        return val.strip().lower() == "true"
    return bool(val)


# ---------------------------------------------------------------------------
# Core split logic
# ---------------------------------------------------------------------------


def _read_lines(filepath: Path) -> list[str] | None:
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            return filepath.read_text(encoding=encoding).splitlines(keepends=True)
        except UnicodeDecodeError:
            continue
    return None


def split_runs(lines: list[str]) -> list[list[str]]:
    """Split raw lines into per-run blocks at each marker occurrence.

    Each block includes its leading marker line through to (but not including)
    the next marker. Returns a list of blocks; length == number of runs found.
    Single-run files return a list of one block.
    """
    split_points = [i for i, ln in enumerate(lines) if MARKER.lower() in ln.lower()]

    if not split_points:
        # No marker at all; treat whole file as one run
        return [lines]

    blocks = []
    for idx, start in enumerate(split_points):
        end = split_points[idx + 1] if idx + 1 < len(split_points) else len(lines)
        blocks.append(lines[start:end])

    return blocks


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------


def _process_file(
    src: Path,
    out_dir: Path,
    dry_run: bool,
    in_place: bool,
) -> bool:
    lines = _read_lines(src)
    if lines is None:
        print(f"  SKIP  {src.name}: could not decode")
        return False

    blocks = split_runs(lines)

    if len(blocks) == 1:
        if not in_place:
            # Copy single-run file to output dir unchanged
            dst = out_dir / src.name
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        print(f"  COPY  {src.name}: 1 run (no split needed)")
        return True

    # Multiple runs; write each block
    stem = src.stem
    suffix = src.suffix

    output_paths = []
    for i, block in enumerate(blocks):
        if i == 0:
            name = src.name  # first run keeps original name
        else:
            name = f"{stem}_split{i:02d}{suffix}"

        dst = (src.parent if in_place else out_dir) / name
        output_paths.append((dst, block))

    print(f"  SPLIT {src.name}: {len(blocks)} runs ->", end="")
    for dst, _ in output_paths:
        print(f" {dst.name}", end="")
    print()

    if not dry_run:
        for dst, block in output_paths:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text("".join(block), encoding="utf-8")

    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Split multi-run CSV files into separate files.",
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
        help="Output folder. Defaults to <data_dir>_split.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Write splits alongside originals, trim originals to first run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without writing anything.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if separate_runs is not set in metadata.yaml.",
    )

    args = parser.parse_args(argv)

    data_dir: Path = args.data_dir.resolve()
    if not data_dir.is_dir():
        print(f"ERROR: {data_dir} is not a directory.")
        return 1

    meta = _load_metadata(data_dir)
    if not _should_split(meta) and not args.force:
        print(
            f"ERROR: separate_runs not set in metadata.yaml in {data_dir}\n\n"
            "Add this to metadata.yaml:\n"
            "  separate_runs: true\n\n"
            "Or use --force to run anyway."
        )
        return 1

    if args.in_place and args.out:
        parser.error("--in-place and --out are mutually exclusive.")

    out_dir: Path
    if args.in_place:
        out_dir = (
            data_dir  # unused for in-place writes but needed for single-run copies
        )
    elif args.out:
        out_dir = args.out.resolve()
    else:
        out_dir = data_dir.parent / (data_dir.name + "_split")

    csv_files = sorted(data_dir.rglob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {data_dir}")
        return 1

    print(f"Data folder : {data_dir}")
    print(f"Output      : {'in-place' if args.in_place else out_dir}")
    print(f"Files       : {len(csv_files)}")
    if args.dry_run:
        print("[dry-run] No files will be written.\n")
    else:
        print()

    ok = sum(_process_file(f, out_dir, args.dry_run, args.in_place) for f in csv_files)
    failed = len(csv_files) - ok

    print(f"\nDone: {ok} succeeded, {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

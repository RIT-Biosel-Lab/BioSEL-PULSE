"""check_windows_paths.py - Pre-upload check: will this package extract on Windows?

Windows refuses to create a path longer than 260 characters (MAX_PATH), and the
Explorer "Extract All" wizard enforces it hard: extraction fails with
"Path too long", sometimes leaving folders silently empty. That budget is spent
on BOTH the folder the user extracts into AND the path inside the archive, so a
file that is fine on macOS and Linux can be unopenable on Windows.

Run this on the assembled package BEFORE uploading to Zenodo. Anything it flags
should be renamed (shorten the filename) or nested less deeply.

Usage
-----
    uv run python Code/BioSEL-PULSE/tools/check_windows_paths.py .
    uv run python Code/BioSEL-PULSE/tools/check_windows_paths.py . --extract-root "C:\\Users\\rbili\\Downloads\\BioSEL_Zenodo_LabInternalTesting"
    uv run python Code/BioSEL-PULSE/tools/check_windows_paths.py . --top 40

By default it assumes the user extracts into a fairly long Downloads path, which
is what people actually do. Pass --extract-root to model a specific one.

Author's Note: I am well aware that this is Agentic AI generated and was a stopgap at the time due to major
issues when testing on Windows. Please take that under considerations that this is meant to help everyone run
without issues. I would clarify that its already been disclosed elsewhere. And I don't have much experiences dealing
with Windows
"""

import argparse
import sys
from pathlib import Path

MAX_PATH = 260

# What a typical Windows user's extraction folder costs, e.g.
# C:\Users\someone\Downloads\BioSEL_Zenodo_Release\  -> ~45 characters.
DEFAULT_EXTRACT_ROOT = r"C:\Users\username\Downloads\BioSEL_Zenodo_Release"

# Windows forbids these in filenames; a name containing one cannot be extracted
# at all, whatever the path length.
ILLEGAL_CHARS = set('<>:"|?*')
RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Never uploaded, and full of paths far longer than anything provided andthe user
# rebuilds .venv themselves with `uv sync`. Skips them as needed :)
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ipynb_checkpoints",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Flag files that will not extract on Windows (MAX_PATH, illegal names)."
    )
    parser.add_argument("folder", help="Folder to scan (the assembled package root).")
    parser.add_argument(
        "--extract-root",
        default=DEFAULT_EXTRACT_ROOT,
        help=f"Windows folder the user will extract into (default: {DEFAULT_EXTRACT_ROOT})",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="How many of the longest paths to list (default: 15)",
    )
    args = parser.parse_args()

    root = Path(args.folder).resolve()
    if not root.is_dir():
        print(f"[ERROR] {root} is not a folder")
        return 1

    # +1 for the backslash joining the extract root to the relative path.
    budget = len(args.extract_root) + 1
    allowed = MAX_PATH - budget

    print("=" * 78)
    print("WINDOWS PATH CHECK")
    print("=" * 78)
    print(f"Scanning:      {root}")
    print(f"Extract root:  {args.extract_root}  ({budget} chars)")
    print(f"Budget left:   {allowed} chars for the path inside the archive")
    print()

    entries = []
    illegal = []
    for p in root.rglob("*"):
        if SKIP_DIRS & set(p.parts):
            continue
        rel = p.relative_to(root)
        rel_str = str(rel).replace("/", "\\")
        entries.append((len(rel_str), rel_str, p.is_dir()))

        name = p.name
        stem = name.split(".")[0].upper()
        if (
            (set(name) & ILLEGAL_CHARS)
            or stem in RESERVED_NAMES
            or name.endswith((" ", "."))
        ):
            illegal.append(rel_str)

    if not entries:
        print("[WARN] Nothing found to scan.")
        return 0

    entries.sort(reverse=True)
    over = [e for e in entries if e[0] > allowed]

    print(f"Longest paths inside the package (top {args.top}):")
    print("-" * 78)
    for length, rel_str, is_dir in entries[: args.top]:
        flag = "TOO LONG" if length > allowed else "ok"
        kind = "dir " if is_dir else "file"
        print(f"  [{flag:>8}] {length:3d}  {kind}  {rel_str}")
    print()

    if illegal:
        print(
            f"[ERROR] {len(illegal)} name(s) Windows cannot create at all "
            f"(illegal character, reserved name, or a trailing space/dot):"
        )
        for rel_str in illegal[:20]:
            print(f"           {rel_str}")
        print()

    if over:
        longest = entries[0][0]
        print(f"[ERROR] {len(over)} path(s) exceed the {allowed}-character budget.")
        print(
            f"        The longest is {longest} chars; it needs to lose at least "
            f"{longest - allowed} characters."
        )
        print()
        print(
            "        Fix by shortening the FILE NAMES (cheapest), or by flattening a folder level."
        )
        print(
            "        Every character you cut is a character of headroom for whoever extracts it"
        )
        print("        into a deeper folder than you modelled here.")
        return 1

    if illegal:
        return 1

    print(f"[OK] All {len(entries)} paths fit, and every name is legal on Windows.")
    print(f"     Longest is {entries[0][0]} chars, {allowed - entries[0][0]} to spare.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

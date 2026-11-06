# tools/

Standalone scripts that do not fit cleanly with the rest of the codes. These are one-off or infrequent operations and not part of the normal `run_analysis.py` pipeline.

Author's Note: Some of those scripts however may be useful and are included for completeness.

---

## add_cycle_column.py

### Background

Early DAQ collections recorded only three columns: `Time_s`, `Pressure_psi`,
`Pot_percent` (Nx3). At some point the DAQ was updated to output a fourth column, `Cycle`, making all new recordings Nx4. The analysis pipeline (`pam_metric_analysis.py`) requires Nx4.

A finite set of legacy Nx3 CSV files were collected before that DAQ update. Rather than adapting the pipeline to handle both formats, this script backfills the missing `Cycle` column on those files so they meet the Nx4 setup. New data will should never need this (I would hope so as cycle # is very useful for identifying fatigue creep, a chronic issues in McKibben Muscles and PAM); it is a one-time fix for the oldest batch of data files collected to help out.

### What it does

Assigns a 1-based integer cycle counter driven by elapsed time:

```
Cycle = floor((Time_s - Time_s[0]) / cycle_duration) + 1
```

Reads `cycle_duration` from a `metadata.yaml` (or `.metadata.yaml`) in the data folder: either a `cycle_duration` key directly, or
`time_window.window_size_seconds` from the existing pipeline metadata format.

Skips any file that already has a `Cycle` column. Output is exactly Nx4:
`[Time_s, Pressure_psi, Pot_percent, Cycle]`.

### Usage

```bash
# Write fixed files to <folder>_cycled/ (default, non-destructive)
uv run python Code/BioSEL-PULSE/tools/add_cycle_column.py /path/to/legacy_folder

# Modify files in place (permanent fix)
uv run python Code/BioSEL-PULSE/tools/add_cycle_column.py /path/to/legacy_folder --in-place

# Custom output folder
uv run python Code/BioSEL-PULSE/tools/add_cycle_column.py /path/to/legacy_folder --out /path/to/output

# Preview without writing anything
uv run python Code/BioSEL-PULSE/tools/add_cycle_column.py /path/to/legacy_folder --dry-run
```

---

## split_runs.py

### Background

Some legacy CSV files contain multiple runs concatenated together, each separated by a `=== THIS IS THE START OF A NEW RUN ===` marker. Splitting these manually across dozens of files was not practical and is better suited with Python automation. **Note: You will need to update the headers if your csv doesn't match.**

### What it does

Scans every CSV in a folder for marker occurrences and splits each multi-run file into separate files. Single-run files are left untouched.

```
example.csv  →  example.csv         (first run)
             →  example_split01.csv (second run)
             →  example_split02.csv (third run, if present)
```

Add to `metadata.yaml` in the data folder:

```yaml
separate_runs: true
```

```bash
# Write to <folder>_split/ (safe default)
uv run python Code/BioSEL-PULSE/tools/split_runs.py /path/to/folder

# Modify originals in place
uv run python Code/BioSEL-PULSE/tools/split_runs.py /path/to/folder --in-place

# Preview without writing
uv run python Code/BioSEL-PULSE/tools/split_runs.py /path/to/folder --dry-run

# Skip the metadata.yaml gate
uv run python Code/BioSEL-PULSE/tools/split_runs.py /path/to/folder --force --dry-run
```

---

## count_samples.py

Reports sample and actuation-cycle counts for every dataset in an
`all_results.pkl`. Useful for verifying total coverage before publication (e.g., confirming 44,516,651 samples across 23,165 cycles). This is actually one of the few tool scripts included that can be expected to be used by general audience (And is already called in the 01_Getting_Started.md).

```bash
# Point it at any all_results.pkl. For the provided Zenodo PKL:
uv run python Code/BioSEL-PULSE/tools/count_samples.py Dataset/all_results.pkl

# Or a PKL you generated with run_analysis.py (default output folder):
uv run python Code/BioSEL-PULSE/tools/count_samples.py analysis_results/all_results.pkl
```

---

## diagnose_nan_ellipse.py

Diagnostic script for investigating datasets that produce NaN ellipse areas. Point it at a folder of known-bad CSV files and it steps through the BioSEL-PULSE one dataset at a time, reporting exactly which guard fired and why without re-running the full set of hundreds of CSVs.

> This may be one of the more useful scripts in here depending on what issues might arise

### Usage

```bash
uv run python Code/BioSEL-PULSE/tools/diagnose_nan_ellipse.py  Data/YourFolder/
```

If the folder uses non-default active-loop settings (check for a
`.metadata.yaml` in that folder):

```bash
uv run python Code/BioSEL-PULSE/tools/diagnose_nan_ellipse.py  Data/YourFolder/  --active-len 5  --delta-p 2.0
```

### What it reports

For each dataset it prints a step-by-step trace through the centroid and ellipse pipeline stages:

| Output                                                          | Meaning                                                 |
| --------------------------------------------------------------- | ------------------------------------------------------- |
| `[ok] All cycles had >2 pts after filter`                       | Data survived the active-loop filter cleanly            |
| `[WARN] N cycle(s) still <=2 pts after filter`                  | Those cycles produced NaN centroids (likely root cause) |
| `[WARN] NaN covariance -> centroid_drift_sum guard fires`       | NaN centroids contaminated `np.cov`                     |
| `[WARN] Near-zero covariance -> centroid_drift_sum guard fires` | All centroids identical (flat/stuck sensor signal)      |
| `[WARN] good_idx has <=1 entry`                                 | Nearly all cycles flagged as Mahalanobis outliers       |
| `[ok] ellipse area = 0.XXXXX`                                   | Ellipse computed successfully, no issue                 |
| `[WARN] ellipse guard fires -> returns NaN area`                | Fewer than 2 valid centroid rows, unrecoverable         |
| `[X] <stage> raised: ...`                                       | That stage threw before it could report anything        |

### When to use this

Run it after seeing `[WARN] Warning ... NaN in ellipse_result.area` in a run. It identifies whether the cause is short cycles (data quality / early-history dataset), a stuck sensor (flat signal), or something else; so you know whether to adjust the active-loop config for that folder or flag the file as bad data.

---

## extract_fulldat.py

Extracts raw time-series data from all CSVs in one or more folders into a single `all_fulldat.pkl` without running any metric computation. Applies the same header detection, encoding fallback, and `.metadata.yaml` unit conversions (PSI→kPa, potentiometer scale) as the main pipeline, then writes each dataset as a `DataFrame` with columns: `Time_s`, `Pressure`, `Contraction`, `Cycle`.

Useful if you want the calibrated, canonical-column signal data without the overhead or output clutter of a full analysis run e.g., for exploratory plotting, custom downstream analysis, or building a lightweight dataset for your uses. It is worth noting that the full pkl already comes with the raw values preserved.

> Author's Note: A pkl file for this is provided in the companion Zenodo Release.

```bash
# Single folder
uv run python Code/BioSEL-PULSE/tools/extract_fulldat.py path/to/FolderA

# Multiple folders in one pass
uv run python Code/BioSEL-PULSE/tools/extract_fulldat.py path/to/FolderA path/to/FolderB

# Named output directory
uv run python Code/BioSEL-PULSE/tools/extract_fulldat.py path/to/FolderA --output my_raw_pkl
```

Output goes in `fulldat_output/` (or your named folder via `--output`) as `all_fulldat.pkl`, created relative to the directory you launch the command from.
Requires a `.metadata.yaml` in the data folder if unit conversions are needed.

---

### metadata.yaml (for add_cycle_column)

Place a `metadata.yaml` in the data folder:

```yaml
# Minimal
cycle_duration: 20 # seconds per cycle
```

Or reuse an existing pipeline `.metadata.yaml`:
`time_window.window_size_seconds` is accepted automatically.

---

## check_windows_paths.py

### Background

Windows cannot create a path longer than 260 characters, and Explorer's built-in extractor enforces that limitation: extraction fails with **"Path too long"**, and can leave folders _silently empty_ rather than stopping. The user then sees the pipeline report that it found no CSVs, which looks like a code bug but is really a half-extracted archive that broke.

The 260 characters are shared between the folder the user extracts into and the path inside the archive. A file that is fine on macOS / Linux can be impossible to extract on Windows purely because the user chose a deep Downloads folder.

### What it does

Scans an assembled package and flags every path that will not survive extraction on Windows, plus any name Windows cannot create at all (illegal characters like `<>:"|?*`, reserved names like `CON` or `COM1`, trailing dots or spaces). It skips `.venv/`, `__pycache__/`, and the other build artefacts that never leaves this package.

This was needed as Lab internal testings showed that this was a major issue with Windows machine (Which is the most common hardware OS in research and needed major add ons to do so). Exit code is non-zero if anything is flagged..

### Usage

```bash
# from the root - models a typical deep Downloads folder
uv run python Code/BioSEL-PULSE/tools/check_windows_paths.py .

# model a specific extraction folder
uv run python Code/BioSEL-PULSE/tools/check_windows_paths.py . --extract-root "C:\\Users\\name\\Downloads\\BioSEL"

# show more of the longest paths
uv run python Code/BioSEL-PULSE/tools/check_windows_paths.py . --top 40
```

Run it **before zipping anything for Zenodo**. See
[`../docs/release/ZENODO_PACKAGING.md`](../docs/release/ZENODO_PACKAGING.md).

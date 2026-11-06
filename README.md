# BioSEL PAM Unified Loading, Synthesis & Extraction (BioSEL-PULSE )

> Author's Note: As stated, the code here is added in here from the time it was attached to the Zenodo upload. Please refer to Zenodo, GitHub Issues or this for recent updates, or the root documentations. The docs/ however contains good sources of information..

Python analysis pipeline for open-loop McKibben Pneumatic Artificial Muscle (PAM) data, accompanying the Bioinspired Systems Engineering Lab (BioSEL) _Data in Brief_ publication. The primary deliverable is the pre-built `.pkl` in the Zenodo release (along with csv files); load it and start analyzing or use it for your research. It serializes the original N×4 CSV values (time, pressure, contraction, cycle) per dataset untouched, plus filtered and derived signal columns (smoothed pressure/contraction, velocity, acceleration) computed with Savitzky-Golay. Metrics dating back to Bryan Lukehart-Yun's M.S. thesis and upcoming publications (hysteresis loop area, centroid drift, cycle-to-cycle correlation, modal distribution) are included on top of the raw data. Researchers can regenerate from the raw CSVs and use any of 11 smoothing methods, but that is entirely optional and left to the researcher's needs.

The published dataset in a provided .pkl file (44,516,651 samples, 23,165 cycles, 6 major muscle specs, 24 operating conditions at its core plus multiple supplementary conditions; the underlying raw CSVs hold roughly 50M samples before active-loop extraction) is distributed via the Zenodo + Data in Brief alongside this code, the raw CSVs, and the Arduino + mechanical step files for the test rig. This pipeline is forward-compatible with new data collected on that rig, or on any DAQ you build to match it. The release packages the Arduino firmware, 3D-printable test-rig step files, and sensor spec sheets so you can reproduce (or adapt) the setup. To feed the BioSEL-PULSE pipeline, either match the DAQ's output columns or adjust the loader to match your CSV files.

**Input**: CSV files included with this release, or data you collect from your own DAQ.
**Output**: `all_results.pkl` + `summary.csv` + auto-generated PKL field guide

> Note: The summary tables are also written as `.xlsx` (Excel).

---

## Viewing Results (read this first)

The terminal viewers `inspect_pkl_results.py` and `plot_pkl_results.py` read the folder that holds `all_results.pkl`. That folder defaults to `analysis_results/`, relative to wherever you launched `run_analysis.py` (the pipeline prints the path when it finishes). If a viewer says "nothing to show," point it at that folder explicitly with `--input`. From the root:

```bash
uv run python Code/BioSEL-PULSE/explore/inspect_pkl_results.py --input Dataset   # metrics table
uv run python Code/BioSEL-PULSE/explore/plot_pkl_results.py   --input Dataset   # figures
```

`--input` takes the folder holding `all_results.pkl`: `Dataset` for the provided Zenodo PKL, `analysis_results` for a default run, or whatever you passed to `--output`. Pass the **folder, not the file**: `--input Dataset/all_results.pkl` fails; `--input Dataset` works. Drop `--input` entirely and the viewers look for `analysis_results/` in your current directory.

The folder name is yours. The **filename is not**: the pipeline always writes `all_results.pkl`, and every viewer looks for that exact name inside the folder you give it. Rename the pkl and nothing will find it (You can modify this if you want to).

---

## Quick Start

**Run everything from the root** (the folder holding `pyproject.toml`). There is one environment for the whole package: one `uv sync`, one `.venv`, no folder to `cd` into. Windows setup steps are in [`../../01_GETTING_STARTED.md`](../../01_GETTING_STARTED.md).

```bash
# 1. Install dependencies (MUST). One time, from the root.
uv sync

# 2. Run the analysis (optional: skip if the provided pkl in Dataset/ is fine).
#    Pick one:
uv run python Code/BioSEL-PULSE/core/run_analysis.py Curated_Data          # regenerate from the provided data
uv run python Code/BioSEL-PULSE/core/run_analysis.py <path/to/your/data>   # or point at your own CSV folder
#    To tune the filtering, edit the .metadata.yaml in the data folder, or start from
#    the annotated template in docs/config_processing/.

# 3. Explore the results. --input is the FOLDER holding all_results.pkl (default: analysis_results/,
#    whose absolute path the run prints when it finishes). Use --input Dataset for the provided PKL.
uv run python Code/BioSEL-PULSE/explore/inspect_pkl_results.py --input <path/to/results>   # metrics, terminal menu
uv run python Code/BioSEL-PULSE/explore/plot_pkl_results.py   --input <path/to/results>   # figures, terminal menu

# 4. Notebook (either works; Jupyter Lab recommended)
uv run jupyter lab Code/BioSEL-PULSE/explore/explore_results.ipynb
uv run jupyter notebook Code/BioSEL-PULSE/explore/explore_results.ipynb
# Or in VS Code: open the root as the folder, then open the notebook. The kernel
# is the root .venv and is detected automatically.
```

> If a run is killed on a machine with limited RAM, cap the worker processes with
> `--workers 4` (or `--workers 1`). Each dataset is processed in its own worker, and each
> worker holds its own copy of the data.

> The commands also work from inside `Code/BioSEL-PULSE/` if you use `../../` data paths, for
> example `uv run python core/run_analysis.py ../../Curated_Data`, because `uv` walks up the
> tree to find the project either way. The root relative form above is what the docs use throughout,
> because it is shorter and covers other files.

> **Data path**: Step 2 accepts any folder path. See [Running on Multiple Folders](#running-on-multiple-folders) for batch usage.

### Regenerate / customize the PKL (optional)

The provided PKL is ready to use as-is. **Regenerate only if you want a different filter than the default Savitzky-Golay**(Smooth Window @ 5), or you're analyzing your own data.

- **Reusing the provided `Curated_Data`:** each dataset folder already comes with a `.metadata.yaml` (this is what produced the canonical PKL). Edit it in place, set `smooth_method` to any of the 11 options (table in [`docs/01_INSTRUCTIONS.md`](docs/01_INSTRUCTIONS.md)), then re-run. A folder's `.metadata.yaml` also applies to any nested folder that doesn't have its own. There is a comprehensive set of comments in most of the `.metadata.yaml` that describes the 11 filtering methods and how to set the parameters for it in the Curated_Data.
- **Your own DAQ data:** copy `docs/config_processing/.metadata.yaml` into your data folder, set `processed` / `analysis_mode` / `smooth_method`, then run.

Each method has its own tuning parameters (not just `smooth_window`); the annotated `.metadata.yaml` template documents them inline per method.

```bash
uv run python Code/BioSEL-PULSE/core/run_analysis.py Curated_Data --output MyRun   # results land in ./MyRun

# Example that goes to Download folder
uv run python Code/BioSEL-PULSE/core/run_analysis.py Curated_Data --output ~/Downloads/MyRun/ # For Linux and MacOS

uv run python Code/BioSEL-PULSE/explore/plot_pkl_results.py --input $Home/Downloads/MyRun # For Windows
```

Then open `explore_results.ipynb` (or run `inspect_pkl_results.py --input MyRun`). Without `--output`, results land in `analysis_results/`, which the notebook and the viewers find on their own (If the `analysis_results/` outputs in Code/BioSEL-PULSE).

### Notes on `explore_results.ipynb` and suggested use on Terminal tools

The notebook is primarily intended to explore the provided PKL from the Zenodo `Dataset/` folder. If you regenerate the PKL locally (e.g. to try the 11 filtering methods), the notebook will detect multiple result sources looking for `analysis_results/` whether its working directory is `BioSEL-PULSE/` or `explore/`. If you sent your run elsewhere with `--output`, it will not be auto-detected; use `customDIR` (see the note below). _**It is recommended that you use the terminal based tools such as inspect_pkl_results.py and plot_pkl_results.py for this instead.**_

- `analysis_results/`: pipeline output from your regenerated run (detected whether the notebook's working directory is `BioSEL-PULSE/` or `explore/`)
- `Dataset`: provided Zenodo PKL

> **Note:** If you used `--output` to redirect pipeline output to a custom folder, the notebook will not find it automatically. Use the `customDIR` variable at the top of the first cell to point to it directly.

---

## What This Computes (based on B. Lukehart-Yun's M.S. thesis and derivative work)

| Metric                        | Description                                                          |
| ----------------------------- | -------------------------------------------------------------------- |
| **Loop Area** (kPa * mm)      | Per-cycle hysteresis area (shoelace), mean, std, normalized value    |
| **Centroid Drift** (kPa * mm) | Per-cycle loop centroid; Mahalanobis outlier detection               |
| **Ellipse Metric** (--)       | 95% confidence ellipse over centroid cloud: area, eccentricity, axes |
| **Cycle Correlation** (--)    | Pearson r between consecutive cycles across 3 domains                |
| **Dip Test** (--)             | Hartigan's dip test on correlation distributions, detects bimodality |

### Optional add-ons (enabled per-folder via `.metadata.yaml`)

**`derived_metrics`**: Adds filtered signals and per-cycle derivatives to `activeDat`:

- `Pressure_filt`, `Contraction_filt`: 11 smoothing methods available (rolling mean, Savitzky-Golay, Butterworth, Bessel, median, Wiener, complementary, Hampel, wavelet, TV, Kalman); see [`docs/01_INSTRUCTIONS.md`](docs/01_INSTRUCTIONS.md) for the full table
- `Velocity_Contraction`, `Velocity_Pressure`, `Acceleration_Contraction`

**`new_metrics`**: Runs `user_metrics.py` on each cycle. Built-in column: `Contraction_Range`. Add your own directly in that file.

---

## Configuration (`.metadata.yaml`)

Copy `docs/config_processing/.metadata.yaml` into any data folder. Every key is documented inline with `#` comments. If no file is present, the pipeline uses safe defaults (pre-processed data, cycle mode).

For validated configs for specific datasets, see [`docs/config_processing/REFERENCE_CONFIGS.md`](docs/config_processing/REFERENCE_CONFIGS.md).

---

## Reading the Output

### `all_results.pkl`

Nested dict indexed by dataset name:

```python
import pickle

results = pickle.load(open("analysis_results/all_results.pkl", "rb"))

ds = results["MyDataset"]
ds["LoopMean"]                       # mean hysteresis loop area
ds["ellipse_result"]["area"]         # centroid ellipse area
ds["activeDat"]                      # active-pressurization window (primary analysis data)
ds["FullDat"]                        # full time-window before active loop extraction
```

See [`docs/03_PKL_OUTPUT_REFERENCE.md`](docs/03_PKL_OUTPUT_REFERENCE.md) for the full key reference, or check `analysis_results/log_output.md` for the auto-generated guide from your last run.

### `summary.csv`

Scalar metrics for every dataset, grouped by source folder: one block per source, separated by `========`. Paste directly into papers or load into Excel.

### Terminal inspection (no plotting needed - if all_results.pkl is in the same folder as you call it)

```bash
uv run python Code/BioSEL-PULSE/explore/inspect_pkl_results.py         # pick dataset from menu
uv run python Code/BioSEL-PULSE/explore/inspect_pkl_results.py MyDS    # jump straight by name (not recommended/unsupported: too many datasets to recall names; use the menu)
```

> Run from the `BioSEL-PULSE/` folder, the bare commands above find `analysis_results/` (the default output folder) on their own. To read a different folder, a `--output` run or the provided Zenodo PKL, point `--input` at it:

```bash
uv run python Code/BioSEL-PULSE/explore/inspect_pkl_results.py --input <path/to/results>

uv run python Code/BioSEL-PULSE/explore/plot_pkl_results.py --input <path/to/results>
```

---

## Running on Multiple Folders

`run_analysis.py` walks subdirectories recursively:

```bash
uv run python Code/BioSEL-PULSE/core/run_analysis.py <path/to/Data/>                    # all subfolders
uv run python Code/BioSEL-PULSE/core/run_analysis.py <path/to/Data/SpecificExperiment>  # one experiment
uv run python Code/BioSEL-PULSE/core/run_analysis.py --output run_01 <path/to/Data/>    # named output folder
```

The `--output` flag writes to the path you name (any relative or absolute path, created if needed). Relative paths, including the default `analysis_results/`, are created in your current directory, i.e. wherever you launch the command. If the target folder already exists, its contents are overwritten in place (no fallback, by design). Omit the flag to use the default.

---

## Extending with `user_metrics.py`

Edit `core/user_metrics.py` to add custom per-cycle columns. The extension point is clearly marked in the file. New columns appear automatically in `activeDat` in the PKL.

Enable in `.metadata.yaml`:

```yaml
new_metrics: true
new_metrics_config:
  my_param: 0.7 # read in user_metrics.py via config.get("my_param", default)
```

Note: user metrics run in time-based mode only (`analysis_mode: "time"`).

---

## Project Structure

This tree is outdated and only focuses on the core/. See the root README.md for more info.

```
BioSEL-PULSE/
│
├── core/
│   ├── run_analysis.py              # Entry point: CSV folder → pkl + summary CSVs
│   ├── pam_metric_analysis.py       # Core analysis library (all metric functions)
│   ├── compute_derived_metrics.py   # Per-cycle signal smoothing and derivatives
│   └── user_metrics.py              # Extension point for custom per-cycle metrics
│
├── explore/
│   ├── explore_results.ipynb        # Interactive exploration notebook
│   ├── inspect_pkl_results.py       # Terminal browser for pkl results
│   └── plot_pkl_results.py          # Plot helper for pkl contents
│
├── docs/
│   ├── 01_INSTRUCTIONS.md           # Step-by-step workflow for new users
│   ├── 02_LIMITATIONS.md            # Known issues and design constraints
│   ├── 03_PKL_OUTPUT_REFERENCE.md   # Full PKL key reference
│   └── config_processing/
│       ├── .metadata.yaml           # Config template, copy to your data folders
│       └── REFERENCE_CONFIGS.md     # Validated configs for specific hardware
│
├── tests/
│   └── test_metrics.py              # Unit tests for core metric functions
│
└── tools/
    ├── add_cycle_column.py          # Utility: add Cycle column to CSVs
    ├── split_runs.py                # Utility: split multi-run CSVs into separate files
    ├── extract_fulldat.py           # Utility: raw CSV → PKL without metric computation
    └── diagnose_nan_ellipse.py      # Diagnostic for NaN ellipse area issues
```

---

## Dependencies

Requires Python 3.11 or newer (pinned as `requires-python = ">=3.11"` in the root's `pyproject.toml`). Managed via [uv](https://github.com/astral-sh/uv). Run `uv sync` **from the root** to install everything; it provisions a matching interpreter for you if one is not already present. The pipeline and the figure notebooks share that single environment.

`numpy`, `pandas`, and `scikit-learn` are pinned to the exact versions that built the published PKL (`numpy==2.4.4`, `pandas==3.0.2`, `scikit-learn==1.8.0`), so it unpickles without version warnings. Also used: `scipy`, `pyyaml`, `matplotlib`, `PyWavelets`, `psutil`, and `openpyxl` (`.xlsx` export). `requirements.txt` at the root carries the same versions for anyone not using uv.

---

## References

- Hartigan's Dip Test: Algorithm AS 217, _Applied Statistics_ (1985) 34(3):322–325
- Van Hooser Lab @ Brandeis University: [Github Link](https://github.com/VH-Lab)

---

## See Also

- [`docs/01_INSTRUCTIONS.md`](docs/01_INSTRUCTIONS.md) - Step-by-step guide for new users
- [`docs/02_LIMITATIONS.md`](docs/02_LIMITATIONS.md) - Known issues and edge cases
- [`docs/03_PKL_OUTPUT_REFERENCE.md`](docs/03_PKL_OUTPUT_REFERENCE.md) - Full PKL key reference
- [`docs/config_processing/REFERENCE_CONFIGS.md`](docs/config_processing/REFERENCE_CONFIGS.md) - Validated processing configs

--- 

## Agentic AI such as Anthropic Claude, ChatGPT Codex, Deepseek, and others


The authors discloses that Agentic AI tools, specifically Claude and Qwen local models, were used to help write and review the BioSEL-PULSE pipeline code to ensure the file paths and commands made sense. Every AI-assisted contribution was read and verified line by line by the lead author before release, under a "trust but verify" process. The companion Data in Brief article states the same disclosure. If any part of the pipeline is unclear, you are welcome to point your own AI assistant at it. 

A `CLAUDE.md` and `AGENTS.md` is included for completeness to help out with the BioSEL-PULSE and also with the Zenodo release to help out as needed. They are contained here, but frozen. BioSEL-FORGE will have the most up to date version as needed. 

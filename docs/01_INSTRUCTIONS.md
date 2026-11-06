# Instructions: BioSEL PAM Analysis Pipeline

Step-by-step guide covering environment setup, data preparation, running analysis, inspecting results, and extending with custom metrics.

---

## Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (package manager)
- CSV data from a BioSEL-compatible DAQ (4 columns: `Time_s`, `Pressure`, `Contraction`, `Cycle`)

```bash
uv sync
# Important since this allows you to download and synchronize packages to make this work. For more information, check the BioSEL Github.
```

> NOTE: If your CSV data collection is having issues following the BioSEL-PULSE, look at core/ to modify the code: `pam_metric_analysis.py` in Line 57 for the markers. Or look at Hardware/'s provided Arduino for how the data is streamed as a sample.

---

## Step 1: Understand Your Data

Before touching the config, answer two questions:

**Is your data already in SI units and scaled?**

- **No (raw)**: Pressure is in PSI, Contraction needs ×1.13 scale → add `.metadata.yaml` with `processed: false`. Assume this is the case unless you know otherwise.
- **Yes (pre-processed)**: Pressure is already in kPa, Contraction already scaled → set `processed: true` or omit the key.

**Which analysis mode?**

- **Time-based** (recommended): Your DAQ controls pressure timing automatically. Group rows into uniform time windows by elapsed time and the `Cycle` column in the CSV is ignored.
- **Cycle-based** (legacy): Your CSV has a reliable `Cycle` column where each number corresponds to one pressurization event started by a human operator and the cycle boundary aligns with the actual pressure event.

If unsure: open a CSV. If cycle 1 starts at an arbitrary point in the pressure profile, use time-based mode.

---

## Step 2: Place Data

```
Data/
├── MyExperiment_Session1/
│   ├── run_001.csv
│   └── .metadata.yaml      ← place here if needed
└── MyExperiment_Session2/
    └── run_001.csv
```

The pipeline walks directories recursively, and you can nest subfolders freely. Settings in `.metadata.yaml` apply to all CSVs in the folder and propagate to subfolders unless overridden.

---

## Step 3: Configure `.metadata.yaml`

If your data needs unit conversion, time-based mode, or non-default active loop parameters, add `.metadata.yaml` to the data folder:

```bash
cp docs/config_processing/.metadata.yaml Data/MyExperiment/
```

Edit it and remove sections you don't need. **No file = pre-processed data, cycle-based mode, pipeline defaults.**

For validated configs for specific hardware setups, see [`docs/config_processing/REFERENCE_CONFIGS.md`](config_processing/REFERENCE_CONFIGS.md).

---

## Step 4: Run the Analysis

```bash
uv run python Code/BioSEL-PULSE/core/run_analysis.py <path/to/Data/MyExperiment/>   # single folder
uv run python Code/BioSEL-PULSE/core/run_analysis.py <path/to/Data/> # all subfolders
uv run python Code/BioSEL-PULSE/core/run_analysis.py <path/to/Data/> --output <path/to/where_you_want_and_rename>   # named output: Example (~/Downloads/Run01)
```

The `--output` flag writes to the path you name, created in your current directory (or an absolute path). If that folder already exists, its contents are overwritten in place. Omit the flag to use the default `analysis_results/` which outputs it in the directory your terminal is set to.

### Output files

All output goes to `analysis_results/` (or your named folder):

| File                    | Description                                                          |
| ----------------------- | -------------------------------------------------------------------- |
| `all_results.pkl`       | Full reproducible analysis such as all metrics, DataFrames, models   |
| `summary.csv`           | Scalar metrics grouped by source folder                              |
| `summary.xlsx`          | Same, formatted for reports (requires `openpyxl`)                    |
| `log_output.md`         | Auto-generated PKL field guide such as keys, shapes, access snippets |
| `log.md`                | Failures and NaN warnings (only written if problems occurred)        |
| `summary_filt.csv/xlsx` | Filtered-signal metrics (only when `derived_metrics: true`)          |

---

## Step 5: Inspect Results

### Terminal inspector (suggested for rapid prototyping and regeneration numerous permutations of the Curated_Data's filtering methods)

```bash
uv run python Code/BioSEL-PULSE/explore/inspect_pkl_results.py          # interactive menu
uv run python Code/BioSEL-PULSE/explore/inspect_pkl_results.py --input  <path/to/where_you_want_and_rename>

# Mot recommended
uv run python Code/BioSEL-PULSE/explore/inspect_pkl_results.py MyDataset  # jump directly by name (Not recommended)
```

> The plot_pkl_results.py also follows the same setup here.

### Jupyter notebook

```bash
uv run jupyter notebook Code/BioSEL-PULSE/explore/explore_results.ipynb

# Note: You can also open explore/explore_results.ipynb directly in VS Code using the Jupyter extension.
```

### Python directly using REPL

Look at this line by line, _**Fair warning: expect the this block to be experimental**_

```python
uv run python -m pickle Dataset/all_results.pkl
uv run --with pandas python        # REPL with pandas available
import pickle
import matplotlib.pyplot as plt

results = pickle.load(open("Dataset/all_results.pkl", "rb"))
results.keys() # To Find the name of the datasets
ds = results["MyDataset"]

print(ds["LoopMean"])
print(ds["ellipse_result"]["area"])

# Want to map it out in REPL?
for k, v in ds.items():
    print(k, "->", type(v).__name__, getattr(v, "shape", ""))

active_df = ds["activeDat"]   # active-window data (primary)
full_df   = ds["FullDat"]     # full time-window data

# Option 1 - Note, the Contraction will look small as they share the same y-axis
full_df.plot(x="Time_s", y=["Pressure", "Contraction"])
plt.show()
# Option 2 - See hysteresis
full_df.plot(x="Pressure", y=["Contraction"])
plt.show()
# option 2b - See Hysteresis and filtered
plt.plot(full_df["Pressure"], full_df["Contraction"], label="Raw")
plt.plot(full_df["Pressure_filt"], full_df["Contraction_filt"], label="Filtered",ls="--", alpha=0.7)
plt.xlabel("Pressure")
plt.ylabel("Contraction")
plt.legend()
plt.show()
# If want to see all 10 for fun
full_df.plot(subplots=True, layout=(5, 2), figsize=(12, 10))
plt.tight_layout()
plt.show()
```

### Auto-generated field guide

`analysis_results/log_output.md` is regenerated on every run. It lists every key in your PKL file output with type, shape, column names, and copy-paste access snippets. It always reflects the exact structure of that run.

---

## Derived Metrics (Signal Processing)

Enable in `.metadata.yaml` to add smoothed signals and per-cycle derivatives to `activeDat`:

```yaml
derived_metrics: true
derived_metrics_config:
  smooth_window: 5
  smooth_method: "savgol" # see table below for all options
```

Columns added: `Pressure_filt`, `Contraction_filt`, `Velocity_Contraction`, `Velocity_Pressure`, `Acceleration_Contraction`.

The 11 methods are provided so researchers can pick what fits their needs regarding the provided data or if they collect their own in time. The published PKL uses Savitzky-Golay (`savgol`) as the standard filtered output. See [`docs/02_LIMITATIONS.md`](02_LIMITATIONS.md) for notes on individual methods, including the Kalman filter.

| Method          | Key params                                                 | Notes                                                                                                                                                                                                                                                                                                                                                                            |
| --------------- | ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rolling_mean`  | `smooth_window`                                            | Centered rolling average. Fast. First row of each cycle is NaN for derivative columns.                                                                                                                                                                                                                                                                                           |
| `savgol`        | `smooth_window`                                            | Savitzky-Golay: Computes derivative analytically in one pass. Best for velocity/acceleration accuracy. **Default for the published PKL.**                                                                                                                                                                                                                                        |
| `butterworth`   | `butterworth_cutoff_hz`, `butterworth_order`               | Zero-phase low-pass (`filtfilt`). Standard in biomechanics. Falls back to `rolling_mean` if cycle is too short.                                                                                                                                                                                                                                                                  |
| `bessel`        | `bessel_cutoff_hz`, `bessel_order`                         | Zero-phase low-pass with maximally flat group delay. Better waveform timing than Butterworth for control applications. Same fallback behavior.                                                                                                                                                                                                                                   |
| `median`        | `smooth_window`                                            | Rolling median. Kills spike/impulse noise from potentiometers. Preserves edges better than rolling mean.                                                                                                                                                                                                                                                                         |
| `wiener`        | `smooth_window`                                            | Adaptive noise filter (`scipy.signal.wiener`). Adjusts attenuation to local signal variance.                                                                                                                                                                                                                                                                                     |
| `complementary` | `complementary_alpha`                                      | Causal first-order IIR: `y[n] = α·x[n] + (1-α)·y[n-1]`. Common in robotics. Introduces phase lag.                                                                                                                                                                                                                                                                                |
| `hampel`        | `smooth_window`, `hampel_threshold`                        | Hampel identifier: Replaces outliers beyond `threshold × 1.4826 × MAD` from local median with that median. Good for encoder glitches.                                                                                                                                                                                                                                            |
| `wavelet`       | `wavelet_name`, `wavelet_level`, `wavelet_threshold_mode`  | Multi-resolution soft/hard thresholding (PyWavelets).                                                                                                                                                                                                                                                                                                                            |
| `tv`            | `tv_weight`                                                | 1-D Total Variation denoising (Chambolle). L1 penalty preserves PAM pressure step edges. Higher weight = more smoothing.                                                                                                                                                                                                                                                         |
| `loess`         | `loess_frac`                                               | **DEPRECATED.** Locally weighted regression (statsmodels LOWESS). **Do not use on raw PAM signals** as it distorts hysteresis loop geometry. Emits a `DeprecationWarning` at runtime. Retained for post-metric application only. Needs the optional extra: `uv sync --extra loess` (since `uv sync` does not install it, and it is not listed in uv.lock and`requirements.txt`). |
| `kalman`        | `kalman_process_noise` (Q), `kalman_measurement_noise` (R) | Scalar linear steady-state Kalman filter. Fixed-gain causal IIR with control-theory parameterization. **Not EKF/UKF**. See Limitations.                                                                                                                                                                                                                                          |

When enabled, `summary_filt.csv` is written with metrics recomputed from the filtered signals.

---

## User Metrics (Custom Extension)

Edit `core/user_metrics.py` to add custom per-cycle columns. Enable per-folder:

```yaml
new_metrics: true
new_metrics_config:
  my_param: 0.7 # accessible via config.get("my_param", default)
```

**What ends up in the PKL:**

- `user_activeDat` | `activeDat` plus any columns you add in `compute_user_metrics()`. The provided example adds `Contraction_Range` (stroke per cycle).
- Any additional top-level keys your `compute_user_metrics()` returns

**Notes:**

- Time-based mode only | not called for `analysis_mode: "cycle"` datasets.
- New column names must not collide with existing pipeline keys (`FullDat`, `activeDat`, `LoopArea_results`, etc.).

---

## Troubleshooting

### "0 datasets found"

- Check that CSVs have a recognized header (`Time_s,` or `Time(s),` after the run marker)
- Check that CSVs are in the folder you passed, not a different nesting level

### "NaN ellipse area" or empty `activeDat`

- The active loop extractor found too few rows per cycle (< 3)
- Usually instant-peak or very short hardware cycles that don't match the default `delta_p`
- Fix: add `.metadata.yaml` with `active_loop: {skip: true}` or lower `delta_p`
- Run `tools/diagnose_nan_ellipse.py` for a detailed diagnostic

### "All cycles failing" / cascade crashes

- Usually a hardware mismatch. Please see [`docs/02_LIMITATIONS.md`](02_LIMITATIONS.md)

### Datasets missing from PKL

- Check `analysis_results/log.md` as it lists which datasets were skipped and why

### `summary.xlsx` not written

- `openpyxl` is a core dependency. Run `uv sync` to ensure it is installed. This should be included in the initial `uv sync`.

### Butterworth fallback warnings

- Normal when a cycle group is too short for `filtfilt` or cutoff exceeds Nyquist
- Falls back to `rolling_mean` automatically or reduce `butterworth_cutoff_hz` or switch to `savgol`

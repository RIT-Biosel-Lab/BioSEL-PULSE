# AGENTS.md

This repo is the SOP for AI coding agents (and a disclosure of AI use) for **BioSEL-PULSE**, the BioSEL PAM Unified Loading, Synthesis & Extraction pipeline. It analyzes open-loop McKibben Pneumatic Artificial Muscle (PAM) data and accompanies the BioSEL *Data in Brief* publication and the Zenodo release (https://zenodo.org/records/23066619).

## Status of this repo

- The code here is **inline with the Zenodo upload** (single initial commit). Treat `core/`, `docs/`, `tests/`, `tools/`, `explore/` as a published, citable snapshot: do not "improve", reformat, rename, or reword them unless the user explicitly asks.
- Do not rewrite or strip the `Author's Note:` / `Author's Notes:` comments in source files and docs. They are immutable as part of the Lab.
- The numerical results in the published `all_results.pkl` come from the code as it stands. Changing metric logic (`core/pam_metric_analysis.py`, `core/compute_derived_metrics.py`) changes published values. Ask first.

## Layout

| Path | Purpose |
| --- | --- |
| `core/` | Pipeline: `run_analysis.py` (entry point), `pam_metric_analysis.py` (loading + metrics), `compute_derived_metrics.py` (filters/derivatives), `user_metrics.py` (user extension point) |
| `explore/` | Viewing results: `inspect_pkl_results.py`, `plot_pkl_results.py`, `explore_results.ipynb` |
| `tools/` | Helper scripts (see `tools/README.md`) |
| `tests/` | pytest suite (see `tests/README.md`) |
| `docs/` | `01_INSTRUCTIONS.md`, `02_LIMITATIONS.md`, `03_PKL_OUTPUT_REFERENCE.md`, `config_processing/` (annotated `.metadata.yaml`), `release/` |

Per-folder behavior is configured by a `.metadata.yaml` in each data folder (template in `docs/config_processing/`).

## Commands

Run from the repo root (where `pyproject.toml` is). One environment, managed by `uv`.

```bash
uv sync                                   # install dependencies
uv run pytest                             # run tests
uv run python core/run_analysis.py <path/to/data>   # regenerate the PKL
```

- `tests/test_metrics.py` is the self-contained suite and should pass.
- `tests/test_app.py` tests a Streamlit viewer that lives in `Visualization/` in the full Zenodo package, which is **not in this repo**. Its tests error here (`FileNotFoundError`). That is expected, not a regression.
- Docs and READMEs show commands with a `Code/BioSEL-PULSE/...` prefix. That is the Zenodo package layout; in this repo the same files sit at the root (`core/...`, `explore/...`).
- Results default to `analysis_results/`, which is gitignored. Do not commit generated outputs, `.venv`, or caches.

## Reading `docs/02_LIMITATIONS.md`

If you summarize it for a user: none of the listed items affect the default run (Savitzky-Golay, `smooth_window: 5`, on the main 120-cycle datasets), which is what produced the provided `all_results.pkl`. They are edge cases for changed filters, short or off-nominal runs, new data, or unusual setups. The severity / "open bug" labels scope one edge case and are not a verdict on the dataset or pipeline.

## Data handling

Per the authors' BioSEL operating procedures, **no research data is fed into AI tools.** Do not upload, paste, or transmit the contents of CSVs, PKLs, or other datasets to any external service. Work from code, schemas, and column names instead.

## AI-use disclosure

As disclosed in the root `README.md` (and the companion *Data in Brief* article): agentic AI tools, specifically Claude and Qwen local models, were used to help write and review the BioSEL-PULSE pipeline code, to make sure file paths and commands made sense. Every AI-assisted contribution was read and verified line by line by the lead author before release ("trust but verify"). The metrics themselves trace back to B. Lukehart-Yun's M.S. thesis work.

Individual files also carry their own notes:

- `tools/check_windows_paths.py`: agentic-AI-generated stopgap for Windows path-length problems.
- `tools/add_cycle_column.py`: written with Claude Haiku, to add a cycle column to the oldest Nx3 CSV batch.
- `tools/extract_fulldat.py`: adapted from `core/` using pseudocode and Claude `/plan`; no data was provided to the model.

Anything an agent contributes later should be disclosed the same way, with an `Author's Note:` in the file's docstring, and verified by a human before release.

`CLAUDE.md` and `AGENTS.md` are frozen with this release. [BioSEL-FORGE](https://github.com/RIT-Biosel-Lab/BioSEL-FORGE) will host the up to date versions.

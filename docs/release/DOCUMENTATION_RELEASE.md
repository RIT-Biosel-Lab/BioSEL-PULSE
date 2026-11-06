# Release Documentation

> **Note:** This document was originally internal to the Lab. It is included in this release so researchers can see how the data was packaged for Zenodo and how choices were made, as well as to reproduce the packaging if needed. This documentation is useful because they may represent useful contributions any extensions works or reproducible attempts can tackle as desired or verify as a whole.

## Numerical Precision & MATLAB Comparison

### Thesis vs. Pipeline Results

The Python pipeline was ported from MATLAB and produces results that match the thesis within **0.3-3.9%**:

| Metric                  | Thesis | Python Pipeline | Difference |
| ----------------------- | ------ | --------------- | ---------- |
| Ellipse Area (Muscle 1) | 0.387  | 0.39605         | 2.3%       |
| Eccentricity (Muscle 2) | 0.609  | 0.60516         | 0.6%       |
| Eccentricity (Muscle 3) | 0.470  | 0.48830         | 3.9%       |
| Eccentricity (Muscle 4) | 0.630  | 0.63734         | 1.2%       |
| Loop Area               | 3.745  | 3.75592         | 0.3%       |

### Why Differences Exist

**Ellipse metrics (0.3-4% variation for those affected, ~60-70% exact match for the rest):**

_Root cause: Mahalanobis distance numerical precision_

Ellipse area depends on Mahalanobis distance:

```
MD = sqrt((x - μ)ᵀ Σ⁻¹ (x - μ))
```

This is numerically sensitive because:

- **Covariance matrix inversion** is ill-conditioned (amplifies rounding errors)
- **Different linear algebra libraries** (MATLAB LAPACK vs NumPy/SciPy LAPACK) use different algorithms
- **Eigenvalue decomposition order** varies between implementations
- **Accumulated floating-point error** through matrix operations

**Root Cause: Tightly Clustered Centroids:**

The hysteresis centroids in this dataset cluster tightly due to the open-loop control model achieving < 1.0 kPa·mm repeatability (90% drift reduction). Tightly clustered data leads to **ill-conditioned covariance matrices**, which are inherently numerically sensitive.

This seems to be well founded and mentioned in multiple papers, and it makes sense that it is not an computational error. The tight clustering affects Mahalanobis precision precisely because of excellent repeatability and how limited sample size could affect it.

**Literature:**

1. Stability of the Mahalanobis Distance: A Technical Note. Andrew D. Ker, Oxford CS Department. Addresses numerical stability of Mahalanobis distance. [Link to Notes](https://www.cs.ox.ac.uk/publications/publication3919-abstract.html)
2. Improved method for correcting sample Mahalanobis distance without estimating population eigenvalues. _International Journal of Data Science and Analytics_ (2019). Documents precision challenges in covariance-based distances. <https://doi.org/10.1007/s41060-019-00201-4>
3. Gavish et al., 10.48550/arXiv.1904.09204 (2019)
   - Addresses eigenvalue/eigenvector sensitivity in high-dimensional settings.
4. Golub & Van Loan, _Matrix Computations_ (3rd ed., 1996). Foundational reference on matrix inversion numerical stability.

**Other metrics (0.3-0.6% variation):**

- Floating-point rounding order
- Default precision display (MATLAB 4 sig figs vs Python 64-bit)
- Numerical library implementation details

### Authority

**The Python pipeline is the reference for this release.** Possible reasons for thesis differences:

- Manual rounding/transcription in thesis document
- Different parameter settings at time of computation
- MATLAB version differences
- Precision loss in thesis formatting (4 significant figures displayed)

### For Users

Use the Python produced results and don't reference the thesis values (treat it as preliminary). The thesis numbers are publicly available for traceability only and are representative of the M.S. Thesis works (which are considered preliminary). Everything is regenerable from the released dataset.

### Reproducibility

All results can be regenerated from the released dataset:

```bash
uv run python Code/BioSEL-PULSE/core/run_analysis.py <path/to/released/data>
```

Results will match `all_results.pkl` within floating-point precision (cross-platform differences in LAPACK implementation may produce up to ~0.01% variation in ellipse metrics, see above),
with one scoped exception: `dip_results["p_value"]` will differ between runs. The dip-test significance level uses a 500-draw bootstrap (`np.random.uniform` in `hartigans_dip_signif_test`) that the author elected to leave unseeded, so the p-values in the released PKL are one such realization of that seed rather than an exactly reproducible number. The dip statistic itself (`DipStat`) is deterministic and will match. Pre-seeding is acknowledged as the correct future fix and is tracked on the GitHub issue tracker (and has been long known with MATLAB's thesis implementations).

---

## Zenodo DOI

Zenodo: [Dataset](https://zenodo.org/records/23066619)

---

## Packaging the Upload

How to split the ~9.5 GB package into a usable Zenodo record (one zip per top-level folder,
environment files loose), and how to check that it will extract on Windows before you upload:
[`ZENODO_PACKAGING.md`](ZENODO_PACKAGING.md).

---

## Known Issues & Limitations

See [`../02_LIMITATIONS.md`](../02_LIMITATIONS.md) for:

- 3-column CSV files (supplementary data)
- Malformed rows (buffer overflow artifacts)
- Git LFS pointer file handling
- Future enhancements planned

# Tests

Two different tests of auditing and testing showcased in here:

- **`test_metrics.py`** ~> unit tests for the core PAM metric functions. Written to pin edge cases found during batch processing of 237 (now 240, after 3 datasets were added late) pipeline-ready datasets (up to 350 total; the remaining ~120 are legacy or incomplete runs, included in the release for completeness but not part of the primary analysis).
- **`test_app.py`** ~> tests the Streamlit viewer in `Visualization/Visualize_Data_App.py`.

## How to run

```
uv run pytest -v          # from the root
```

Everything should pass in a few seconds. The visualization suite drives the real app through
Streamlit's tests, so it is a little slower than the pure metric tests.

## What is tested

### `TestPolyarea`

Verifies `_polyarea` (shoelace formula) against shapes with known exact areas: a unit square, a right triangle, and collinear points (zero area). Everything downstream of loop area depends on this function being correct regarding Hysteresis Metrics. It would be ideal if this is correct as Centroid Drift for 95% confidence of ellipse area needs a somewhat complete computed area.

### `TestCentroidDriftSum`

Three cases:

- **Clean cycles**: normal synthetic data, confirms centroids are computed and tracks the expected trend across cycles.
- **All-identical values**: all pressure and contraction readings are the same and producing a singular (zero) covariance matrix. Previously this could cause unstable matrix inversion; now treated as all-inlier with no Mahalanobis step.
- **Short cycles (≤2 points)**: cycles with too few points to compute a mean produce NaN centroids. Confirms the function returns cleanly without crashing rather than propagating undefined behaviour downstream.

### `TestEllipseMetric`

Four cases covering `ellipse_metric_for_centroid`:

- **Clean cloud**: confirms a valid positive area is returned from a normal centroid distribution.
- **All-NaN input**: the primary bug this suite was written to catch (see background below). Confirms the function returns a NaN sentinel dict rather than silently producing NaN area through a poisoned covariance matrix.
- **Empty DataFrame**: confirms the existing length guard still works.
- **Single row**: confirms one centroid point cannot define an ellipse.

### `TestCombinedPolyarea`

Two cases:

- **Empty DataFrame**: confirms the existing guard returns NaN stats rather than raising.
- **Known ellipse loops**: synthetic cycles that trace an ellipse with
  semi-axes 5 and 3. Confirms the computed mean loop area matches π × 5 × 3 within 1%.

### `test_app.py`

Drives `Visualization/Visualize_Data_App.py` through Streamlit's own test harness against a synthetic PKL, so
it checks what the app actually renders rather than what its source looks like:

- it loads a results folder and draws the figures
- both cycle sliders work when dragged, and the single-cycle tab draws the filtered loop under
  the raw one
- a dataset processed without `derived_metrics` still renders, with an explanation instead of an
  empty panel
- a bad results folder produces a message, not a traceback
- the headline metrics do **not** follow the cycle slider. They are the `summary.csv` numbers and
  describe the whole run; if they recomputed from whatever slice the slider sits on, the app would
  display numbers that contradict the released summary table

## Background: why these edge cases matter

During batch processing, a consistent 4–5 datasets out of 237 produced NaN ellipse areas. The root cause traced to 20-cycle datasets (Spring2026's ShortBurstRuns) where the active-loop filter stripped some cycles down to ≤2 data points. Those cycles produced NaN centroids.

The bug was found within `ellipse_metric_for_centroid`: `np.cov` has no NaN-ignoring mode, so even one NaN centroid row out of 20 contaminated the entire 2×2 covariance matrix, making all eigenvalues NaN and therefore area = π × NaN × NaN. The failure was silent and no exception existed, which propagated alll the way to the end.

The fix filters NaN rows before calling `np.cov`, so the ellipse is computed on whichever centroids are valid. A NaN area is only returned when fewer than 2 valid centroid rows remain, at which point there's nothing to fit. If you extend MATLAB's polyarea or use the Shoelace Theorem manually to compute the values, getting the values and computing everything is possible. However, at the time of the 2026 release, it was considered low on the priority due to time constraints.

120-cycle datasets (which makes up majority of the data being released) triggered this because the DAQ setup produced consistent pressure rises that survive the active-loop filter intact when configurated. The 20-cycle datasets exposed the assumption and it may be reasonable that future data extended or collected in your own extension that short cycle datasets will expose have this issue.

## Expected warnings

One test (`test_short_cycles_produce_nan_centroids_no_crash`) intentionally creates all-NaN centroids and will produce numpy `RuntimeWarning` messages about mean/median of empty slices. These are expected; they confirm numpy is handling the all-NaN summary statistics gracefully rather than raising.

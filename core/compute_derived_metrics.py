"""compute_derived_metrics.py | Derivatives for PAM data.

Adds Setpoint (Proxy of Solenoid States), Velocity_Contraction, Acceleration_Contraction, Velocity_Pressure columns
directly onto FullDat and activeDat DataFrames. Time-based mode only as Cycle mode had become legacy
by this point already.

Smoothing methods:
    rolling_mean  - centered rolling mean (default if nothing is stated)
    savgol        - Savitzky-Golay polynomial fit; computes derivative and smooths in one pass
    butterworth   - zero-phase Butterworth low-pass on raw signal, then np.gradient for derivative
    median        - rolling median; kills impulse/spike noise, preserves edges
    wiener        - adaptive Wiener filter (scipy); adjusts attenuation to local variance
    complementary - first-order causal IIR: y[n] = alpha*x[n] + (1-alpha)*y[n-1]
    bessel        - zero-phase Bessel low-pass; maximally flat group delay vs Butterworth
    hampel        - Hampel identifier; spike removal via median ± k·MAD, then de-spiked signal
    wavelet       - wavelet soft/hard thresholding (PyWavelets); multi-resolution denoising
    tv            - 1-D Total Variation denoising; L1 regularization, preserves step edges
    loess         - [DEPRECATED] locally weighted regression (statsmodels LOWESS); DO NOT USE on raw
                    PAM signals as it distorts hysteresis loop geometry; kept for post-metric use only
    kalman        - steady-state scalar Kalman filter; Q/R noise ratio controls smoothing (not EKF or UKF; read docs for more info)

-- Author's Note --
Author's Note: The canonical pkl file provided uses the Savgol with Smoothwindows = 5 as this was considered
the most broad filter that would work for general purpose. Feel free to finetune. However, there may exist
edge cases where certain filter may not work, so be forewarned that this could occur.

-- Disclaimers by Author and BioSEL --
It is to the best knowledge by the authors and that derived / inferred metrics may not match what usecases
the researchers or such analysis would require. If this is such case like but not limited to:
    * Setpoints may require additional finetuning, the setpoint was set up to follow hard time limits for the period
        e.g. 10 second period with 50% duty cycle aims to follow that, BUT from the time the pressure rise started. So this
        needs to be finetuned as needed.
    * Same applies to filtering; those filterings were implemented based on Literature / known resourcee and only for directly on
        the raw columns to do so. If they do not meet the desired implementation, feel free to finetune or modify (see following below).
    * Same applies to any filtered hysteresis metrics that relies on the filtered values, please refer to forthcoming papers
        that is soon to be released later this year - Signed July 31, 2026 by B. Lukehart-Yun.

Long story short, if there's anything off or just doesnt meet your edgecases, just go ahead and modify at your discretion. The biggest
things to note is most certainly the setpoint (since that correspond to pressure input) given numerous permutations that each signals
processing filter has, there most certainly exists any given number of combination that will break the computation (which is why log.md
is created if some csv dataset broke the computation). It is worth noting that this research code is STILL experimental and may require
further finetuning / if any mistakes occurs, please just modify the codes to correct it and note that in your research notes.

It is totally well within the user's bounds to modify such codes in here under MIT License especially to get what analysis calls for.

Lastly, please create a Git issue on the linked GitHub repository if any fix is needed or derive as needed in a research derivative for your
research.
"""

from __future__ import annotations

import warnings
import numpy as np
import pandas as pd
from scipy.signal import (
    savgol_filter,
    butter,
    filtfilt,
    lfilter,
    wiener as _wiener_filter,
    bessel as _bessel_design,
)

try:
    import pywt as _pywt
except ImportError:
    _pywt = None

try:
    from statsmodels.nonparametric.smoothers_lowess import lowess as _lowess
except ImportError:
    _lowess = None


def _clean(arr: np.ndarray) -> np.ndarray:
    """Linearly interpolate NaN/inf so signal filters receive a finite array and not break the system"""
    a = arr.copy().astype(float)
    bad = ~np.isfinite(a)
    if bad.any():
        idx = np.arange(len(a))
        a[bad] = np.interp(idx[bad], idx[~bad], a[~bad]) if (~bad).any() else 0.0
    return a


def _safe_t_vals(t: np.ndarray) -> np.ndarray:
    """Return t with zero/negative diffs replaced by the minimum positive dt.

    Prevents np.gradient divide-by-zero when Time_s has duplicate timestamps (which
    happens when the data is at resting states when it is 0)
    """
    dt = np.diff(t)
    if not np.any(dt <= 0):
        return t
    pos = dt[dt > 0]
    min_dt = float(pos.min()) if len(pos) else 1e-6
    dt_safe = np.where(dt <= 0, min_dt, dt)
    return np.concatenate([[t[0]], t[0] + np.cumsum(dt_safe)])


def _hampel_filter(arr: np.ndarray, window: int, threshold: float) -> np.ndarray:
    """Hampel identifier: replace outliers with local median.

    A sample is an outlier when |x[i] - median(neighbors)| > threshold * 1.4826 * MAD.
    The 1.4826 factor makes MAD a consistent estimator of sigma under Gaussian noise.
    """
    s = pd.Series(arr)
    rolling_med = s.rolling(window, center=True, min_periods=1).median()
    rolling_mad = s.rolling(window, center=True, min_periods=1).apply(
        lambda x: float(np.median(np.abs(x - np.median(x)))), raw=True
    )
    outliers = (
        np.abs(arr - rolling_med.values) > threshold * 1.4826 * rolling_mad.values
    )
    out = arr.copy()
    out[outliers] = rolling_med.values[outliers]
    return out


def _tv_denoise_1d(y: np.ndarray, weight: float, n_iter: int = 100) -> np.ndarray:
    """1-D Total Variation denoising via Chambolle's dual algorithm.

    Minimizes (1/2)||x - y||^2 + weight * sum_i |x[i+1] - x[i]|.
    Higher weight = more smoothing; preserves step edges (L1 penalty on differences).
    """
    n = len(y)
    if n < 2:
        return y.copy()

    def _div(p_: np.ndarray) -> np.ndarray:
        d = np.zeros(n)
        d[0] = -p_[0]
        d[1:-1] = p_[:-1] - p_[1:]
        d[-1] = p_[-1]
        return d

    p = np.zeros(n - 1)
    tau = 0.24  # step size < 1/||D||^2 = 1/4 for 1-D finite differences
    for _ in range(n_iter):
        x = y - _div(p)
        p = np.clip(p + tau * np.diff(x), -weight, weight)
    return y - _div(p)


def compute_derivatives(
    df: pd.DataFrame,
    smooth_window: int = 5,
    delta_p: float = 0.5,
    smooth_method: str = "rolling_mean",
    butterworth_cutoff_hz: float = 10.0,
    butterworth_order: int = 4,
    complementary_alpha: float = 0.3,
    bessel_cutoff_hz: float = 10.0,
    bessel_order: int = 4,
    hampel_threshold: float = 3.0,
    wavelet_name: str = "db4",
    wavelet_level: int | None = None,
    wavelet_threshold_mode: str = "soft",
    tv_weight: float = 0.1,
    loess_frac: float = 0.1,
    kalman_process_noise: float = 1e-3,
    kalman_measurement_noise: float = 0.1,
) -> pd.DataFrame:
    """Add Setpoint, filtered signals, and per-cycle velocity/acceleration columns.

    Derivatives are computed per-cycle so they never bleed across window boundaries.
    Setpoint is detected from cycle 1's pressure rise/fall and applied as a 0/1 template
    to all cycles and are pegged to actual pressure events, not fixed time offsets.

    Adds 6 columns: Setpoint, Pressure_filt, Contraction_filt,
    Velocity_Contraction, Acceleration_Contraction, Velocity_Pressure.
    (Author's Notes: Those 6 new columns are well founded in literature for broadest uses in analysis
    the only thing missing is force profile which isn't easy to collect, but documentations references or mentions
    it along with test rig sharing)

    butterworth/bessel fall back to rolling_mean if a cycle is too short or cutoff
    exceeds Nyquist. loess is deprecated for raw PAM signals as it distorts hysteresis geometry.
    """
    df = df.copy()
    cycles = sorted(df["Cycle"].dropna().unique())

    if not cycles:
        for col in [
            "Setpoint",
            "Pressure_filt",
            "Contraction_filt",
            "Velocity_Contraction",
            "Velocity_Pressure",
            "Acceleration_Contraction",
        ]:
            df[col] = np.nan
        return df

    # Detect rise/fall from cycle 1 and use as Setpoint template for all cycles.
    # Baseline = mean of first 5% of samples (at-rest pressure before actuation).
    cyc1 = df[df["Cycle"] == cycles[0]]
    press1 = cyc1["Pressure"].values
    t1_rel = cyc1["Time_s"].values - cyc1["Time_s"].values.min()
    n_base = max(3, len(press1) // 20)
    baseline = press1[:n_base].mean()
    i_above = np.where(press1 > baseline + delta_p)[0]
    has_setpoint = len(i_above) > 0
    if has_setpoint:
        t_rise = t1_rel[i_above[0]]
        t_fall = t1_rel[i_above[-1]]

    use_savgol = smooth_method == "savgol"
    use_butterworth = smooth_method == "butterworth"
    use_bessel = smooth_method == "bessel"

    # savgol window_length must be odd and >= 3
    wl = smooth_window if smooth_window % 2 == 1 else smooth_window + 1
    wl = max(wl, 3)

    # Butterworth / Bessel filter coefficients, was designed once from first cycle's dt.
    # Recomputed per-cycle only if dt changes (unlikely for fixed DAQ).
    _bw_b, _bw_a = None, None
    _bw_fs_cached = None
    _bs_b, _bs_a = None, None
    _bs_fs_cached = None

    if smooth_method == "wavelet" and _pywt is None:
        raise ImportError("PyWavelets is required for wavelet smoothing. Run: uv sync")
    if smooth_method == "loess" and _lowess is None:
        raise ImportError(
            "statsmodels is required for loess smoothing. It is an optional extra, so "
            "plain `uv sync` will not install it. Run: uv sync --extra loess"
        )
    if smooth_method == "loess":
        warnings.warn(
            "smooth_method='loess' is deprecated for raw PAM signals. LOESS distorts hysteresis "
            "loop geometry and is NOT recommended. Use savgol, wavelet, or tv instead.",
            DeprecationWarning,
            stacklevel=2,
        )

    parts = []
    for cycle_id in cycles:
        grp = df[df["Cycle"] == cycle_id].copy()

        if has_setpoint:
            t_within = grp["Time_s"].values - grp["Time_s"].values.min()
            grp["Setpoint"] = ((t_within >= t_rise) & (t_within <= t_fall)).astype(int)
        else:
            grp["Setpoint"] = 0

        if use_savgol:
            diffs = grp["Time_s"].diff().dropna()
            dt_uniform = float(np.median(diffs)) if len(diffs) > 0 else 1.0

            if len(grp) <= wl:
                # Cycle too short for savgol window, fall back to rolling mean
                print(
                    f"  [WARN] Savgol fallback (cycle {cycle_id}): "
                    f"n={len(grp)} samples < window={wl} → using rolling_mean"
                )
                dt = grp["Time_s"].diff()
                vel_c = grp["Contraction"].diff() / dt
                vel_p = grp["Pressure"].diff() / dt
                acc_c = vel_c.diff() / dt
                grp["Pressure_filt"] = (
                    grp["Pressure"]
                    .rolling(smooth_window, center=True, min_periods=1)
                    .mean()
                )
                grp["Contraction_filt"] = (
                    grp["Contraction"]
                    .rolling(smooth_window, center=True, min_periods=1)
                    .mean()
                )
                grp["Velocity_Contraction"] = vel_c.rolling(
                    smooth_window, center=True, min_periods=1
                ).mean()
                grp["Velocity_Pressure"] = vel_p.rolling(
                    smooth_window, center=True, min_periods=1
                ).mean()
                grp["Acceleration_Contraction"] = acc_c.rolling(
                    smooth_window, center=True, min_periods=1
                ).mean()
            else:
                grp["Pressure_filt"] = savgol_filter(
                    _clean(grp["Pressure"].values), wl, polyorder=2, deriv=0
                )
                grp["Contraction_filt"] = savgol_filter(
                    _clean(grp["Contraction"].values), wl, polyorder=2, deriv=0
                )
                grp["Velocity_Contraction"] = savgol_filter(
                    _clean(grp["Contraction"].values),
                    wl,
                    polyorder=2,
                    deriv=1,
                    delta=dt_uniform,
                )
                grp["Velocity_Pressure"] = savgol_filter(
                    _clean(grp["Pressure"].values),
                    wl,
                    polyorder=2,
                    deriv=1,
                    delta=dt_uniform,
                )
                grp["Acceleration_Contraction"] = savgol_filter(
                    _clean(grp["Contraction"].values),
                    wl,
                    polyorder=2,
                    deriv=2,
                    delta=dt_uniform,
                )

        elif use_butterworth:
            diffs = grp["Time_s"].diff().dropna()
            dt_uniform = float(np.median(diffs)) if len(diffs) > 0 else 1.0
            fs = 1.0 / dt_uniform if dt_uniform > 0 else 1.0
            nyq = 0.5 * fs
            cutoff_norm = butterworth_cutoff_hz / nyq
            min_len = 3 * (butterworth_order + 1) + 1  # filtfilt minimum

            if cutoff_norm >= 1.0 or len(grp) <= min_len:
                # Fall back to rolling mean, cycle too short or cutoff exceeds Nyquist
                print(
                    f"  [WARN] Butterworth fallback (cycle {cycle_id}): "
                    f"cutoff={butterworth_cutoff_hz}Hz, Nyquist={nyq:.1f}Hz, "
                    f"n={len(grp)} samples (min={min_len}) → using rolling_mean"
                )
                dt = grp["Time_s"].diff()
                vel_c = grp["Contraction"].diff() / dt
                vel_p = grp["Pressure"].diff() / dt
                acc_c = vel_c.diff() / dt
                grp["Pressure_filt"] = (
                    grp["Pressure"]
                    .rolling(smooth_window, center=True, min_periods=1)
                    .mean()
                )
                grp["Contraction_filt"] = (
                    grp["Contraction"]
                    .rolling(smooth_window, center=True, min_periods=1)
                    .mean()
                )
                grp["Velocity_Contraction"] = vel_c.rolling(
                    smooth_window, center=True, min_periods=1
                ).mean()
                grp["Velocity_Pressure"] = vel_p.rolling(
                    smooth_window, center=True, min_periods=1
                ).mean()
                grp["Acceleration_Contraction"] = acc_c.rolling(
                    smooth_window, center=True, min_periods=1
                ).mean()
            else:
                # Design filter if fs changed or first cycle
                if fs != _bw_fs_cached:
                    _bw_b, _bw_a = butter(butterworth_order, cutoff_norm, btype="low")
                    _bw_fs_cached = fs

                t_vals = _safe_t_vals(grp["Time_s"].values)
                pot_filt = filtfilt(_bw_b, _bw_a, _clean(grp["Contraction"].values))
                press_filt = filtfilt(_bw_b, _bw_a, _clean(grp["Pressure"].values))

                # np.gradient: central differences interior, one-sided at edges, no boundary NaN
                vel_c = np.gradient(pot_filt, t_vals)
                vel_p = np.gradient(press_filt, t_vals)
                acc_c = np.gradient(vel_c, t_vals)

                grp["Pressure_filt"] = press_filt
                grp["Contraction_filt"] = pot_filt
                grp["Velocity_Contraction"] = vel_c
                grp["Velocity_Pressure"] = vel_p
                grp["Acceleration_Contraction"] = acc_c

        elif smooth_method == "median":
            t_vals = _safe_t_vals(grp["Time_s"].values)
            press_filt = (
                pd.Series(_clean(grp["Pressure"].values))
                .rolling(smooth_window, center=True, min_periods=1)
                .median()
                .values
            )
            cont_filt = (
                pd.Series(_clean(grp["Contraction"].values))
                .rolling(smooth_window, center=True, min_periods=1)
                .median()
                .values
            )
            vel_c = np.gradient(cont_filt, t_vals)
            vel_p = np.gradient(press_filt, t_vals)
            acc_c = np.gradient(vel_c, t_vals)
            grp["Pressure_filt"] = press_filt
            grp["Contraction_filt"] = cont_filt
            grp["Velocity_Contraction"] = vel_c
            grp["Velocity_Pressure"] = vel_p
            grp["Acceleration_Contraction"] = acc_c

        elif smooth_method == "wiener":
            t_vals = _safe_t_vals(grp["Time_s"].values)
            press_filt = _wiener_filter(
                _clean(grp["Pressure"].values), mysize=smooth_window
            )
            cont_filt = _wiener_filter(
                _clean(grp["Contraction"].values), mysize=smooth_window
            )
            vel_c = np.gradient(cont_filt, t_vals)
            vel_p = np.gradient(press_filt, t_vals)
            acc_c = np.gradient(vel_c, t_vals)
            grp["Pressure_filt"] = press_filt
            grp["Contraction_filt"] = cont_filt
            grp["Velocity_Contraction"] = vel_c
            grp["Velocity_Pressure"] = vel_p
            grp["Acceleration_Contraction"] = acc_c

        elif smooth_method == "complementary":
            # Causal first-order IIR: y[n] = alpha*x[n] + (1-alpha)*y[n-1]
            t_vals = _safe_t_vals(grp["Time_s"].values)
            b_iir = [complementary_alpha]
            a_iir = [1.0, -(1.0 - complementary_alpha)]
            press_filt = lfilter(b_iir, a_iir, _clean(grp["Pressure"].values))
            cont_filt = lfilter(b_iir, a_iir, _clean(grp["Contraction"].values))
            vel_c = np.gradient(cont_filt, t_vals)
            vel_p = np.gradient(press_filt, t_vals)
            acc_c = np.gradient(vel_c, t_vals)
            grp["Pressure_filt"] = press_filt
            grp["Contraction_filt"] = cont_filt
            grp["Velocity_Contraction"] = vel_c
            grp["Velocity_Pressure"] = vel_p
            grp["Acceleration_Contraction"] = acc_c

        elif use_bessel:
            diffs = grp["Time_s"].diff().dropna()
            dt_uniform = float(np.median(diffs)) if len(diffs) > 0 else 1.0
            fs = 1.0 / dt_uniform if dt_uniform > 0 else 1.0
            nyq = 0.5 * fs
            cutoff_norm = bessel_cutoff_hz / nyq
            min_len = 3 * (bessel_order + 1) + 1

            if cutoff_norm >= 1.0 or len(grp) <= min_len:
                print(
                    f"  [WARN] Bessel fallback (cycle {cycle_id}): "
                    f"cutoff={bessel_cutoff_hz}Hz, Nyquist={nyq:.1f}Hz, "
                    f"n={len(grp)} samples (min={min_len}) → using rolling_mean"
                )
                dt = grp["Time_s"].diff()
                vel_c = grp["Contraction"].diff() / dt
                vel_p = grp["Pressure"].diff() / dt
                acc_c = vel_c.diff() / dt
                grp["Pressure_filt"] = (
                    grp["Pressure"]
                    .rolling(smooth_window, center=True, min_periods=1)
                    .mean()
                )
                grp["Contraction_filt"] = (
                    grp["Contraction"]
                    .rolling(smooth_window, center=True, min_periods=1)
                    .mean()
                )
                grp["Velocity_Contraction"] = vel_c.rolling(
                    smooth_window, center=True, min_periods=1
                ).mean()
                grp["Velocity_Pressure"] = vel_p.rolling(
                    smooth_window, center=True, min_periods=1
                ).mean()
                grp["Acceleration_Contraction"] = acc_c.rolling(
                    smooth_window, center=True, min_periods=1
                ).mean()
            else:
                if fs != _bs_fs_cached:
                    # norm='mag': -3dB point at cutoff_norm, same convention as butterworth
                    _bs_b, _bs_a = _bessel_design(
                        bessel_order, cutoff_norm, btype="low", norm="mag"
                    )
                    _bs_fs_cached = fs
                t_vals = _safe_t_vals(grp["Time_s"].values)
                cont_filt = filtfilt(_bs_b, _bs_a, _clean(grp["Contraction"].values))
                press_filt = filtfilt(_bs_b, _bs_a, _clean(grp["Pressure"].values))
                vel_c = np.gradient(cont_filt, t_vals)
                vel_p = np.gradient(press_filt, t_vals)
                acc_c = np.gradient(vel_c, t_vals)
                grp["Pressure_filt"] = press_filt
                grp["Contraction_filt"] = cont_filt
                grp["Velocity_Contraction"] = vel_c
                grp["Velocity_Pressure"] = vel_p
                grp["Acceleration_Contraction"] = acc_c

        elif smooth_method == "hampel":
            t_vals = _safe_t_vals(grp["Time_s"].values)
            press_filt = _hampel_filter(
                _clean(grp["Pressure"].values), smooth_window, hampel_threshold
            )
            cont_filt = _hampel_filter(
                _clean(grp["Contraction"].values), smooth_window, hampel_threshold
            )
            vel_c = np.gradient(cont_filt, t_vals)
            vel_p = np.gradient(press_filt, t_vals)
            acc_c = np.gradient(vel_c, t_vals)
            grp["Pressure_filt"] = press_filt
            grp["Contraction_filt"] = cont_filt
            grp["Velocity_Contraction"] = vel_c
            grp["Velocity_Pressure"] = vel_p
            grp["Acceleration_Contraction"] = acc_c

        elif smooth_method == "wavelet":
            t_vals = _safe_t_vals(grp["Time_s"].values)

            def _wavelet_denoise(arr: np.ndarray) -> np.ndarray:
                level = wavelet_level or _pywt.dwt_max_level(len(arr), wavelet_name)
                coeffs = _pywt.wavedec(arr, wavelet_name, level=level)
                # Universal threshold estimated from finest detail coefficients
                sigma_est = np.median(np.abs(coeffs[-1])) / 0.6745
                thresh = sigma_est * np.sqrt(2.0 * np.log(max(len(arr), 2)))
                coeffs[1:] = [
                    _pywt.threshold(c, thresh, mode=wavelet_threshold_mode)
                    for c in coeffs[1:]
                ]
                rec = _pywt.waverec(coeffs, wavelet_name)
                return rec[: len(arr)]  # waverec may produce n+1 samples at some levels

            press_filt = _wavelet_denoise(_clean(grp["Pressure"].values))
            cont_filt = _wavelet_denoise(_clean(grp["Contraction"].values))
            vel_c = np.gradient(cont_filt, t_vals)
            vel_p = np.gradient(press_filt, t_vals)
            acc_c = np.gradient(vel_c, t_vals)
            grp["Pressure_filt"] = press_filt
            grp["Contraction_filt"] = cont_filt
            grp["Velocity_Contraction"] = vel_c
            grp["Velocity_Pressure"] = vel_p
            grp["Acceleration_Contraction"] = acc_c

        elif smooth_method == "tv":
            t_vals = _safe_t_vals(grp["Time_s"].values)
            press_filt = _tv_denoise_1d(_clean(grp["Pressure"].values), tv_weight)
            cont_filt = _tv_denoise_1d(_clean(grp["Contraction"].values), tv_weight)
            vel_c = np.gradient(cont_filt, t_vals)
            vel_p = np.gradient(press_filt, t_vals)
            acc_c = np.gradient(vel_c, t_vals)
            grp["Pressure_filt"] = press_filt
            grp["Contraction_filt"] = cont_filt
            grp["Velocity_Contraction"] = vel_c
            grp["Velocity_Pressure"] = vel_p
            grp["Acceleration_Contraction"] = acc_c

        elif smooth_method == "loess":
            t_vals = _safe_t_vals(grp["Time_s"].values)
            idx = np.arange(len(t_vals), dtype=float)
            press_filt = _lowess(
                _clean(grp["Pressure"].values),
                idx,
                frac=loess_frac,
                return_sorted=False,
            )
            cont_filt = _lowess(
                _clean(grp["Contraction"].values),
                idx,
                frac=loess_frac,
                return_sorted=False,
            )
            vel_c = np.gradient(cont_filt, t_vals)
            vel_p = np.gradient(press_filt, t_vals)
            acc_c = np.gradient(vel_c, t_vals)
            grp["Pressure_filt"] = press_filt
            grp["Contraction_filt"] = cont_filt
            grp["Velocity_Contraction"] = vel_c
            grp["Velocity_Pressure"] = vel_p
            grp["Acceleration_Contraction"] = acc_c

        elif smooth_method == "kalman":
            # Steady-state scalar Kalman filter.
            # Solves the scalar DARE analytically: P^2 - Q*P - Q*R = 0
            # → P∞ = (Q + √(Q²+4QR))/2,  K∞ = P∞/(P∞+R)
            # Reduces to a fixed-gain causal IIR identical in structure to
            # complementary, but K is derived from physically interpretable
            # Q (process noise) and R (measurement noise) instead of a raw alpha.
            # Author's Note: Do note that this is not the Extended Kalman Filter
            Q = kalman_process_noise
            R_n = kalman_measurement_noise
            P_ss = (Q + np.sqrt(Q**2 + 4.0 * Q * R_n)) / 2.0
            K_ss = P_ss / (P_ss + R_n)
            t_vals = _safe_t_vals(grp["Time_s"].values)
            b_k = [K_ss]
            a_k = [1.0, -(1.0 - K_ss)]
            press_filt = lfilter(b_k, a_k, _clean(grp["Pressure"].values))
            cont_filt = lfilter(b_k, a_k, _clean(grp["Contraction"].values))
            vel_c = np.gradient(cont_filt, t_vals)
            vel_p = np.gradient(press_filt, t_vals)
            acc_c = np.gradient(vel_c, t_vals)
            grp["Pressure_filt"] = press_filt
            grp["Contraction_filt"] = cont_filt
            grp["Velocity_Contraction"] = vel_c
            grp["Velocity_Pressure"] = vel_p
            grp["Acceleration_Contraction"] = acc_c

        else:
            dt = grp["Time_s"].diff()  # NaN at first row of each cycle and intentional
            vel_c = grp["Contraction"].diff() / dt
            vel_p = grp["Pressure"].diff() / dt
            acc_c = vel_c.diff() / dt
            grp["Pressure_filt"] = (
                grp["Pressure"]
                .rolling(smooth_window, center=True, min_periods=1)
                .mean()
            )
            grp["Contraction_filt"] = (
                grp["Contraction"]
                .rolling(smooth_window, center=True, min_periods=1)
                .mean()
            )
            grp["Velocity_Contraction"] = vel_c.rolling(
                smooth_window, center=True, min_periods=1
            ).mean()
            grp["Velocity_Pressure"] = vel_p.rolling(
                smooth_window, center=True, min_periods=1
            ).mean()
            grp["Acceleration_Contraction"] = acc_c.rolling(
                smooth_window, center=True, min_periods=1
            ).mean()

        parts.append(grp)

    return pd.concat(parts).sort_index()

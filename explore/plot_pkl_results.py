"""plot_pkl_results.py - Plot PAM results from all_results.pkl.

Generates up to 6 figures per dataset (time series, derived metrics, phase portrait,
raw vs filtered hysteresis). Figures 2-4 require derived_metrics columns in activeDat.
Cycles are overlaid and colormap-coded early→late. Change _CMAP to swap globally.

Usage:
    uv run python explore/plot_pkl_results.py                   # interactive picker
    uv run python explore/plot_pkl_results.py dataset_name      # plot one dataset and exit
    uv run python explore/plot_pkl_results.py --input <folder>  # read a specific results folder

Author's Note: This is one of MY favorite tools to use, since I can easily iterate and view the 6 pops up figures like
MATLAB was (It is intentional that this terminal tool was to emulate MATLAB's figures :)
"""

import argparse
import pickle
import sys
from pathlib import Path

import matplotlib.cm as cm
import matplotlib.pyplot as plt
import numpy as np


_CMAP = "magma"  # swap here to change colormap globally: "inferno", "plasma", "magma", etc. See matplotlib for more info on sequential gradients
_DERIVED_COLS = (
    "Velocity_Contraction",
    "Velocity_Pressure",
    "Acceleration_Contraction",
)
_DEFAULT_DIR = Path(
    "analysis_results"
)  # cwd-relative, matches run_analysis.py's default output


def _resolve_results_dir(requested: str | None) -> Path:
    if requested is None:
        return _DEFAULT_DIR

    req = Path(requested)
    if not req.is_absolute():
        req = Path.cwd() / req

    if (req / "all_results.pkl").exists():
        return req

    print(
        f"[WARN] '{requested}' not found or missing all_results.pkl - falling back to default '{_DEFAULT_DIR.name}'"
    )

    if not (_DEFAULT_DIR / "all_results.pkl").exists():
        print(
            f"[ERROR] Default folder '{_DEFAULT_DIR}' also has no all_results.pkl - nothing to show."
        )
        print("   Generate results:  uv run python core/run_analysis.py <path/to/data>")
        print(
            "   Or, if the pkl is elsewhere, point --input at the folder holding all_results.pkl."
        )
        sys.exit(1)

    return _DEFAULT_DIR


def load_results(results_dir: Path):
    pkl_path = results_dir / "all_results.pkl"
    if not pkl_path.exists():
        print(f"[ERROR] {pkl_path} not found")
        print("   Generate results:  uv run python core/run_analysis.py <path/to/data>")
        print(
            "   Or, if the pkl is elsewhere, point --input at the folder holding all_results.pkl."
        )
        sys.exit(1)
    with open(pkl_path, "rb") as f:
        return pickle.load(f)


def _setpoint_twin(ax, t_rel, setpoint, alpha=0.55):
    """Overlay Setpoint step signal on a right twin-axis. Autoscales like MATLAB yyaxis."""
    color = "#AAAAAA"
    ax2 = ax.twinx()
    ax2.step(t_rel, setpoint, where="post", color=color, alpha=alpha, linewidth=1.0)
    ax2.set_yticks([0, 1])
    ax2.set_yticklabels(["0", "1"], color=color, fontsize=7)
    ax2.set_ylabel("Setpoint", color=color, fontsize=8)
    ax2.spines["right"].set_color(color)
    ax2.tick_params(axis="y", colors=color)


def _add_colorbar(fig, ax, n_cycles):
    sm = cm.ScalarMappable(cmap=_CMAP, norm=plt.Normalize(vmin=1, vmax=n_cycles))
    sm.set_array([])
    fig.colorbar(sm, ax=ax, label=f"Cycle (1–{n_cycles})", shrink=0.8)


def plot_dataset(ds_name, data):
    """Generate Figure 1, and (if derived metrics present) Figure 2 and Figure 3."""
    full_dat = data.get("FullDat")
    active_dat = data.get("activeDat")

    if full_dat is None or full_dat.empty:
        print(f"  [WARN] FullDat missing or empty for '{ds_name}', skipping.")
        return

    cycles = sorted(full_dat["Cycle"].dropna().unique())
    n_cyc = len(cycles)
    colors = plt.get_cmap(_CMAP)(np.linspace(0, 1, max(n_cyc, 1)))
    has_setpoint = "Setpoint" in full_dat.columns

    # -- Figure 1: Time Series (Pressure and Contraction vs Time) -------------
    fig1, (ax_p, ax_c) = plt.subplots(1, 2, figsize=(12, 5))
    fig1.suptitle(f"{ds_name}  -  Raw Signals", fontsize=12, fontweight="bold")

    t_all = full_dat["Time_s"].values
    ax_p.plot(t_all, full_dat["Pressure"].values, linewidth=1.5, color="#1f77b4")
    ax_c.plot(t_all, full_dat["Contraction"].values, linewidth=1.5, color="#d62728")

    ax_p.set(xlabel="Time (s)", ylabel="Pressure (kPa)", title="Time vs Pressure")
    ax_p.grid(True, alpha=0.4)
    ax_c.set(xlabel="Time (s)", ylabel="Contraction (mm)", title="Time vs Contraction")
    ax_c.grid(True, alpha=0.4)

    if has_setpoint:
        _setpoint_twin(ax_p, t_all, full_dat["Setpoint"].values)
        _setpoint_twin(ax_c, t_all, full_dat["Setpoint"].values)

    fig1.tight_layout()
    try:
        fig1.canvas.manager.set_window_title(f"Raw Signals - {ds_name}")
    except Exception:
        pass

    # -- Figure 2: Derived metrics time-series
    # FullDat also carries all derived columns - Figures 2–4 use activeDat for the
    # tighter active window, but swap full_dat/cycles to plot over the full signal.
    has_derived = (
        active_dat is not None
        and not active_dat.empty
        and all(col in active_dat.columns for col in _DERIVED_COLS)
    )

    if not has_derived:
        print(f"  [INFO] No derived metrics for '{ds_name}' - Figure 1 only.")
        print(
            f"     Add derived_metrics: true to .metadata.yaml and re-run run_analysis.py."
        )
        plt.show(block=False)
        return

    act_cycles = sorted(active_dat["Cycle"].dropna().unique())
    n_act = len(act_cycles)
    act_colors = plt.get_cmap(_CMAP)(np.linspace(0, 1, max(n_act, 1)))
    has_sp_act = "Setpoint" in active_dat.columns

    fig2, (ax_vp, ax_vc, ax_ac) = plt.subplots(
        1, 3, figsize=(15, 6), layout="constrained"
    )
    fig2.suptitle(f"{ds_name}  -  Derived Metrics", fontsize=12, fontweight="bold")

    # Each cycle plotted at absolute time so x-axis reads as a continuous timeline.
    for i, cyc in enumerate(act_cycles):
        cyc_df = active_dat[active_dat["Cycle"] == cyc]
        t_abs = cyc_df["Time_s"].values
        col = act_colors[i]
        ax_vp.plot(
            t_abs,
            cyc_df["Velocity_Pressure"].values,
            color=col,
            linewidth=1.5,
            alpha=0.7,
        )
        ax_vc.plot(
            t_abs,
            cyc_df["Velocity_Contraction"].values,
            color=col,
            linewidth=1.5,
            alpha=0.7,
        )
        ax_ac.plot(
            t_abs,
            cyc_df["Acceleration_Contraction"].values,
            color=col,
            linewidth=1.5,
            alpha=0.7,
        )

    ax_vp.set(
        xlabel="Time (s)", ylabel="dPressure/dt (kPa/s)", title="Pressure Rise Rate"
    )
    ax_vp.grid(True, alpha=0.3)
    ax_vc.set(
        xlabel="Time (s)", ylabel="dContraction/dt (mm/s)", title="Contraction Velocity"
    )
    ax_vc.grid(True, alpha=0.3)
    ax_ac.set(
        xlabel="Time (s)",
        ylabel="d²Contraction/dt² (mm/s²)",
        title="Contraction Acceleration",
    )
    ax_ac.grid(True, alpha=0.3)

    if has_sp_act:
        _setpoint_twin(
            ax_vp, active_dat["Time_s"].values, active_dat["Setpoint"].values, alpha=0.2
        )
        _setpoint_twin(
            ax_vc, active_dat["Time_s"].values, active_dat["Setpoint"].values, alpha=0.2
        )
        _setpoint_twin(
            ax_ac, active_dat["Time_s"].values, active_dat["Setpoint"].values, alpha=0.2
        )

    sm2 = cm.ScalarMappable(cmap=_CMAP, norm=plt.Normalize(vmin=1, vmax=n_act))
    sm2.set_array([])
    fig2.colorbar(
        sm2,
        ax=[ax_vp, ax_vc, ax_ac],
        orientation="horizontal",
        label=f"Cycle (1–{n_act})",
        shrink=0.4,
        pad=0.12,
    )
    try:
        fig2.canvas.manager.set_window_title(f"Derived Metrics - {ds_name}")
    except Exception:
        pass

    # -- Figure 3: Global Hysteresis | Velocity Phase Portrait
    fig3, (ax_h, ax_ph) = plt.subplots(1, 2, figsize=(12, 5))
    fig3.suptitle(
        f"{ds_name}  -  Hysteresis & Phase Portrait", fontsize=12, fontweight="bold"
    )

    for i, cyc in enumerate(cycles):
        cyc_df = full_dat[full_dat["Cycle"] == cyc]
        ax_h.plot(
            cyc_df["Pressure"].values,
            cyc_df["Contraction"].values,
            color=colors[i],
            linewidth=1.2,
            alpha=0.7,
        )

    for i, cyc in enumerate(act_cycles):
        cyc_df = active_dat[active_dat["Cycle"] == cyc]
        ax_ph.plot(
            cyc_df["Contraction"].values,
            cyc_df["Velocity_Contraction"].values,
            color=act_colors[i],
            linewidth=1.2,
            alpha=0.7,
        )

    ax_h.set(
        xlabel="Pressure (kPa)",
        ylabel="Contraction (mm)",
        title="Global Hysteresis Loop",
    )
    ax_h.grid(True, alpha=0.3)
    ax_ph.set(
        xlabel="Contraction (mm)",
        ylabel="Contraction Velocity (mm/s)",
        title="Velocity Phase Portrait",
    )
    ax_ph.grid(True, alpha=0.3)

    _add_colorbar(fig3, ax_h, n_cyc)
    _add_colorbar(fig3, ax_ph, n_act)
    fig3.tight_layout()
    try:
        fig3.canvas.manager.set_window_title(f"Hysteresis & Phase Portrait - {ds_name}")
    except Exception:
        pass

    # -- Figure 4: Raw vs Filtered Hysteresis (activeDat)
    fig4, (ax_raw, ax_filt) = plt.subplots(1, 2, figsize=(12, 5))
    fig4.suptitle(
        f"{ds_name}  -  Raw vs Filtered Hysteresis", fontsize=12, fontweight="bold"
    )

    for i, cyc in enumerate(act_cycles):
        cyc_df = active_dat[active_dat["Cycle"] == cyc]
        ax_raw.plot(
            cyc_df["Pressure"].values,
            cyc_df["Contraction"].values,
            color=act_colors[i],
            linewidth=1.2,
            alpha=0.7,
        )
        ax_filt.plot(
            cyc_df["Pressure_filt"].values,
            cyc_df["Contraction_filt"].values,
            color=act_colors[i],
            linewidth=1.2,
            alpha=0.7,
        )

    ax_raw.set(
        xlabel="Pressure (kPa)",
        ylabel="Contraction (mm)",
        title="Active Hysteresis (raw)",
    )
    ax_raw.grid(True, alpha=0.3)
    ax_filt.set(
        xlabel="Pressure filtered (kPa)",
        ylabel="Contraction filtered (mm)",
        title="Active Hysteresis (filtered)",
    )
    ax_filt.grid(True, alpha=0.3)

    _add_colorbar(fig4, ax_raw, n_act)
    _add_colorbar(fig4, ax_filt, n_act)
    fig4.tight_layout()
    try:
        fig4.canvas.manager.set_window_title(f"Raw vs Filtered Hysteresis - {ds_name}")
    except Exception:
        pass

    plt.show(block=False)


def _has_derived(data):
    act = data.get("activeDat")
    return (
        act is not None
        and hasattr(act, "columns")
        and all(col in act.columns for col in _DERIVED_COLS)
    )


def interactive_picker(all_results):
    """Let user pick a dataset from a numbered list."""
    names = sorted(all_results.keys())
    print(f"\n{len(names)} dataset(s) in pkl:\n")
    for i, name in enumerate(names, 1):
        loop_mean = all_results[name].get("LoopMean", "?")
        loop_str = (
            f"{loop_mean:.4f}" if isinstance(loop_mean, float) else str(loop_mean)
        )
        e = all_results[name].get("ellipse_result", {})
        area = e.get("area", "?")
        area_str = f"{area:.4f}" if isinstance(area, float) else str(area)
        print(f"  {i:3d}. {name:40} loop_mean={loop_str:12} ellipse_area={area_str:12}")
    print("\nEnter number or name (or 'q' to quit): ", end="", flush=True)
    choice = input().strip()
    if choice.lower() == "q":
        return None
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(names):
            return names[idx]
    except ValueError:
        pass
    if choice in names:
        return choice
    print(f"[ERROR] Not found: '{choice}'")
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Plot PAM results from all_results.pkl"
    )
    parser.add_argument(
        "dataset",
        nargs="?",
        help="Dataset name to plot (default: interactive picker)",
    )
    parser.add_argument(
        "--input",
        metavar="DIRNAME",
        default=None,
        help="Results folder to read from (default: analysis_results)",
    )
    args = parser.parse_args()

    results_dir = _resolve_results_dir(args.input)
    all_results = load_results(results_dir)

    if args.dataset:
        ds_name = args.dataset
        if ds_name not in all_results:
            print(f"[ERROR] Dataset '{ds_name}' not found.")
            print(f"   Available: {sorted(all_results.keys())}")
            sys.exit(1)
        print(f"Plotting '{ds_name}'...")
        plot_dataset(ds_name, all_results[ds_name])
    else:
        while True:
            ds_name = interactive_picker(all_results)
            if ds_name is None:
                print("\nGoodbye.")
                break
            print(f"\nPlotting '{ds_name}'...")
            plot_dataset(ds_name, all_results[ds_name])
            print("\n" + "-" * 60)
            input(
                "Press Enter to close plots and pick another dataset (or Ctrl-C to quit)..."
            )
            plt.close("all")
            print()


if __name__ == "__main__":
    main()

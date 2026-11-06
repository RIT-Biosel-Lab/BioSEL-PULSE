"""Tests for the Streamlit viewer in Visualization/Visualize_Data_App.py.

Drives the real app through Streamlit's own AppTest harness against a synthetic PKL, so
these check what the app renders and not the actual data as needed.

Author's Note: Same thing here, received feedback that Jupyter was broken, due to time constraints, needed to adapt portion for Streamlit usage and ported it over
"""

import pickle
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use("Agg")

_APP = Path(__file__).resolve().parents[3] / "Visualization" / "Visualize_Data_App.py"


def _dataset() -> dict:
    """A dataset dict shaped like one entry of all_results.pkl, with derived metrics included."""
    rows = []
    for cyc in range(1, 4):
        t = np.linspace(0, 6, 60)
        p = 40 * (1 - np.exp(-t / 1.2))
        c = 0.28 * p
        rows.append(
            pd.DataFrame(
                {
                    "Time_s": (cyc - 1) * 10 + t,
                    "Pressure": p,
                    "Contraction": c,
                    "Cycle": cyc,
                    "Setpoint": (t < 6).astype(int),
                    "Pressure_filt": p,
                    "Contraction_filt": c,
                    "Velocity_Pressure": np.gradient(p, t),
                    "Velocity_Contraction": np.gradient(c, t),
                    "Acceleration_Contraction": np.gradient(np.gradient(c, t), t),
                }
            )
        )
    df = pd.concat(rows, ignore_index=True)
    return {
        "FullDat": df,
        "activeDat": df,
        "_source": "Test/Source",
        "LoopMean": 1.0,
        "LoopSTD": 0.1,
        "NormLoopValue": 0.5,
        "CentroidDrift_summary": [{"mean": 1.0, "std": 0.1}, {"mean": 2.0, "std": 0.2}],
        "ellipse_result": {"area": 3.0, "eccentricity": 0.9},
    }


@pytest.fixture
def pkl_dir(tmp_path) -> str:
    """A results folder holding a two-dataset all_results.pkl, for the app to open."""
    with open(tmp_path / "all_results.pkl", "wb") as f:
        pickle.dump({"DatasetA": _dataset(), "DatasetB": _dataset()}, f)
    return str(tmp_path)


@pytest.fixture
def app(pkl_dir):
    """The real app, pointed at that folder, already run once."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(_APP), default_timeout=120)
    at.run()
    at.sidebar.text_input[0].set_value(pkl_dir).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_app_loads_a_pkl_and_draws_its_figures(app):
    assert {"Raw Signals", "Derived Metrics"} <= {h.value for h in app.subheader}
    assert app.title[0].value == "DatasetA"


def test_cycle_slider_narrows_the_figures(app):
    app.sidebar.slider[0].set_range(2, 3).run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("Drawing cycles **2-3**" in c.value for c in app.caption)


def test_metrics_do_not_follow_the_cycle_slider(app):
    """The headline numbers are the summary.csv numbers: they describe the whole run.

    If they recomputed from whatever slice the slider sits on, the app would display
    numbers that disagree with the released summary table.
    """
    before = [m.value for m in app.metric]
    app.sidebar.slider[0].set_range(2, 3).run()
    assert not app.exception, [e.value for e in app.exception]
    assert [m.value for m in app.metric] == before


def test_single_cycle_slider(app):
    cycle_sliders = [s for s in app.slider if s.label == "Cycle"]
    assert cycle_sliders, "the single-cycle slider is gone"
    cycle_sliders[0].set_value(2).run()
    assert not app.exception, [e.value for e in app.exception]


def test_single_cycle_shows_the_filtered_counterpart(app):
    """The filtered loop is drawn under the raw one, for a dataset that has one."""
    assert any("after filtering" in c.value for c in app.caption)


def test_metrics_table_omits_the_source_column(app):
    table = app.dataframe[0].value
    assert "Source" not in table.columns
    assert "Dataset" in table.columns and "EllipseArea" in table.columns


def test_app_reports_a_bad_results_folder(app):
    """The most likely user error must produce a message, not a traceback."""
    app.sidebar.text_input[0].set_value("/nope/not/here").run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("all_results.pkl" in e.value for e in app.error)


def test_dataset_without_derived_metrics_still_renders(tmp_path):
    """A dataset processed without derived_metrics gets Figure 1 and an explanation."""
    from streamlit.testing.v1 import AppTest

    plain = _dataset()
    drop = [
        "Velocity_Contraction",
        "Velocity_Pressure",
        "Acceleration_Contraction",
        "Pressure_filt",
        "Contraction_filt",
    ]
    plain["FullDat"] = plain["FullDat"].drop(columns=drop)
    plain["activeDat"] = plain["activeDat"].drop(columns=drop)

    folder = tmp_path / "plain"
    folder.mkdir()
    with open(folder / "all_results.pkl", "wb") as f:
        pickle.dump({"PlainDS": plain}, f)

    at = AppTest.from_file(str(_APP), default_timeout=120)
    at.run()
    at.sidebar.text_input[0].set_value(str(folder)).run()

    assert not at.exception, [e.value for e in at.exception]
    assert "Raw Signals" in {h.value for h in at.subheader}
    assert any("derived_metrics" in i.value for i in at.info)

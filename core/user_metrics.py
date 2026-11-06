"""user_metrics.py - Custom per-cycle column metrics.

Add your own metrics here. They run automatically on any dataset where
`new_metrics: true` is set in the folder's .metadata.yaml. I however cannot
claim beyond what is listed here will work perfectly with what you have:

It may be suggested you run your own analysis by calling the .pkl as it comes
with FullDat of the CSV values.

 How to add a metric
 1. Add computation inside compute_user_metrics() in the marked section.
 2. `grp` is a single-cycle slice of activeDat with columns:
       Time_s, Pressure, Contraction, Cycle
    If derived_metrics is also enabled:
       Setpoint, Pressure_filt, Contraction_filt,
       Velocity_Contraction, Velocity_Pressure, Acceleration_Contraction
 3. Assign: grp["My_Metric"] = <expression>
 4. Enable in .metadata.yaml: new_metrics: true
 5. Optional config via .metadata.yaml new_metrics_config:
       my_param: 0.7  →  config.get("my_param", default_value)

 Results are incorporated in the PKL as user_activeDat, joined to activeDat via Cycle:
    results["DatasetName"]["user_activeDat"]["My_Metric"]
 activeDat is not modified directly; this aims to avoids pd.concat deconsolidation bloat
    Note: This balloons the .pkl easily as it mutates and double counts which is where the GB can balloon

-- Author's Note --
Author's Note: This was an issue resolved awhile ago where it would add GBs of data, if this happens: I would
suggest taking a look here. I've checked and this was resolved, the PKL size went down from 9.5 GB down to 4.3 GB so success!

This is likely where the GB size during regeneration could occur. Be mindful that this is one such way to add your own metrics / analysis
The other way is to modify the codes directly as needed and go from there.

Note: Make sure the .metadata.yaml's `new_metrics: true` is active. The Zenodo release has it set to true.

An example is set below below, please read the comments. (July 31, 2026 - there is a slight chance I'll rewrite this to make it easier and put
the live version on the BioSEL GitHub and Zenodo if time permits)
"""

from __future__ import annotations

import pandas as pd


def compute_user_metrics(
    df: pd.DataFrame,
    config: dict | None = None,
    full_df: pd.DataFrame | None = None,  # noqa: ARG001 (available for baseline reference)
) -> dict:
    """Compute user-defined per-cycle metrics. Called when new_metrics: true in .metadata.yaml.

    df is read-only (activeDat). full_df is FullDat, available for resting-state baseline.
    Returns a dict merged into the PKL; keys must not collide with core pipeline keys.
    """
    config = config or {}
    cycles = sorted(df["Cycle"].dropna().unique())

    if not cycles:
        return {}

    parts = []
    for cycle_id in cycles:
        grp = df[df["Cycle"] == cycle_id].copy()

        # -- ADD YOUR METRICS BELOW
        #
        # Assign new columns to `grp`. Each column appears in user_activeDat
        # in the PKL, joinable back to activeDat via Cycle.
        # Read optional config values with: config.get("key", default)
        #
        # Contraction_Range: stroke length per cycle (max minus min contraction).
        # Constant across all rows in the cycle; useful as an inferred or
        # derived feature since a fair portion of the data were computed post processing..
        # Author's Note: This was added as a demonstration how to make this work while making sure
        # this would be useful to the audience as needed.
        grp["Contraction_Range"] = grp["Contraction"].max() - grp["Contraction"].min()
        #
        # -- END EXTENSION POINT

        parts.append(grp)

    user_dat = pd.concat(parts).sort_index()

    # Return only new columns + Cycle as join key; activeDat stays untouched.
    new_cols = [c for c in user_dat.columns if c not in df.columns]
    return {"user_activeDat": user_dat[["Cycle"] + new_cols].reset_index(drop=True)}

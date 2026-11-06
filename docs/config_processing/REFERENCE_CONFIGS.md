### BioSEL_OriginalData

```yaml
processed: true
analysis_mode: "time"
time_window:
  window_size_seconds: 20
active_loop:
  delta_p: 3.44738
  active_len: 6.0
  backup_time: 0.5

derived_metrics: true
derived_metrics_config:
  smooth_window: 5 # optional, defaults to 5
  smooth_method: "savgol"
  #smooth_method: "butterworth"
  #butterworth_cutoff_hz: 10.0
  #butterworth_order: 4
new_metrics: true
# optional overrides:
#new_metrics_config:
#pressure_bin_size: 0.5           # change bin width from default 1.0 psi
#aggregate_by_pressure: true      # also produce t3_binned in the PKL
```

## Spring2026_ExtendedData - 5ms

```yaml
processed: false

conversions:
  psi_to_kpa: true
  pot_percent_scale_factor: 1.13

analysis_mode: "time"
time_window:
  window_size_seconds: 10
active_loop:
  skip: true
note: "10 second period, elected to not use active lens here"

derived_metrics: true
derived_metrics_config:
  smooth_window: 5 # optional, defaults to 5
  smooth_method: "savgol"

new_metrics: true
# optional overrides:
#new_metrics_config:
#pressure_bin_size: 0.5           # change bin width from default 1.0 psi
#aggregate_by_pressure: true      # also produce t3_binned in the PKL
```

## Spring2026_ExtendedData - 10 ms (Should work with the BioSELOriginalData)

```yaml
processed: false

conversions:
  psi_to_kpa: true
  pot_percent_scale_factor: 1.13

analysis_mode: "time"
time_window:
  window_size_seconds: 20
active_loop:
  delta_p: 3.44738
  active_len: 6.0
  backup_time: 0.5

derived_metrics: true
derived_metrics_config:
  smooth_window: 5 # optional, defaults to 5
  smooth_method: "savgol"

new_metrics: true
```

## SUPERLATIVE - Case by case basis

Spring2026's Datasets

- Short Burst Runs for Troubleshooting

```yaml
processed: false

conversions:
  psi_to_kpa: true
  pot_percent_scale_factor: 1.13

analysis_mode: "time"
time_window:
  window_size_seconds: 20
active_loop:
  delta_p: 3.44738
  active_len: 6.0
  backup_time: 0.5

derived_metrics: true
derived_metrics_config:
  smooth_window: 5
  #smooth_method: "savgol"
  smooth_method: "butterworth"
  butterworth_cutoff_hz: 10.0
  butterworth_order: 4
new_metrics: true
```

- Thick Muscle Issues and Troubleshooting

```yaml
processed: false

conversions:
  psi_to_kpa: true
  pot_percent_scale_factor: 1.13

analysis_mode: "time"
time_window:
  window_size_seconds: 20
active_loop:
  delta_p: 3.44738
  active_len: 6.0
  backup_time: 0.5

derived_metrics: true
derived_metrics_config:
  smooth_window: 5
  smooth_method: "savgol"

new_metrics: true
```

- Thin 100mm 10ms and 10 second period

```yaml
processed: false

conversions:
  psi_to_kpa: true
  pot_percent_scale_factor: 1.13

analysis_mode: "time"
time_window:
  window_size_seconds: 10
active_loop:
  skip: true

derived_metrics: true
derived_metrics_config:
  smooth_window: 5
  smooth_method: "savgol"

new_metrics: true
```

---

# results/

Outputs of `experiments/` land here. Commit them: judges want job IDs and reproducible numbers.

| File | Written by |
|---|---|
| `benchmark_<fleet>.json` | `python -m experiments.benchmark` |
| `shots_sweep[_tag].csv` | `python -m experiments.shots_sweep` (milestone 4) |
| `hardware_runs.csv` | `src/hardware.log_run` (every qBraid job: device, kind, job ID, shots, status) |
| `counts/<job_id>.json` | raw counts for each completed qBraid job |
| `hardware_hour<h>_<device>.png` | `python -m experiments.hardware_run` |

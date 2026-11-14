# Architecture

The upstream starter notebook has been split into modules so the notebooks, tests and experiment scripts all run the **same code**.
Fill in TODOs in `src/`; the notebooks pick up edits through `%autoreload`.

```
data/                 plants*.csv, demand*.csv, README (license, provenance), make_data.py
src/
  check.py            organizers' checker + MILP (READ-ONLY; only the DATA path changed)
  config.py           constants (BLOCK_MW, N_SLACK, SHOT_GRID, DEVICES, COLORS) + Problem / load_problem()
  classical.py        cheapest_first  [TODO 1] · run_milp · run_rule · run_classical
  qubo.py             plant_hour_costs [TODO 2] · build_qubo [TODO 3] · add_locks · brute force · bit helpers
  quantum.py          qubo_to_ising · qaoa_circuit · run_qaoa · choice_probs   (needs qiskit)
  scheduler.py        schedule_day (hour-by-hour loop, sampler="qaoa" | "random") · run_day
  hardware.py         build_hardware_circuit · run_aer · submit_qbraid (QPU guard) · log_run · choice_shares
  plotting.py         plot_demand · plot_schedule · plot_choice_probs · plot_comparison · plot_hardware_vs_sim
  maxcut.py           QAOA primer: qaoa_circuit [TODO cost layer] · optimize [TODO optimizer] · read_out · brute_force
notebooks/
  starter.ipynb       the upstream starter flow, calling src/
  qaoa_primer.ipynb   the upstream Max-Cut primer, calling src/maxcut.py
experiments/          python -m experiments.<name>   (run from the repo root)
  benchmark.py        MILP vs rule vs QAOA vs random → results/benchmark_<fleet>.json      (milestones 2, 4)
  hour_check.py       QUBO brute force vs exact best, per hour                              (milestone 3)
  shots_sweep.py      QAOA vs random × shots × seeds → results/shots_sweep.csv              (milestone 4, required)
  hardware_run.py     one hour on a qBraid device, logged to results/hardware_runs.csv      (milestone 5)
tests/                pytest; tests for unfinished TODOs SKIP with the TODO named
reference/upstream/   untouched copies of the organizers' notebooks, check.py and README
results/              outputs of experiments (keep job IDs here)
```

## Data flow for one day

```
load_problem() ─► Problem(plants, demand, reserve)
                     │
     ┌───────────────┼──────────────────────────────┐
     ▼               ▼                              ▼
 run_milp()     cheapest_first()          schedule_day()  for t in 0..23:
 (exact)        (TODO 1)                    locks(history)            ─ classical
                                            build_qubo(was_on) [TODO 2,3]
                                            add_locks(...)
                                            run_qaoa / random  → probs ─ quantum (or random)
                                            sample `shots` bitstrings
                                            keep cheapest valid (hour_ok, hour_cost) ─ classical
                                            was_on ← pick
     │               │                              │
     └───────────────┴──────────► check_schedule(...) ─► cost, gap vs MILP, violations
```

## Conventions

- **Schedule:** `int` array `(hours, plants)`, `1` = on.
- **Qubit order:** qubits `0..n-1` are plants, then `n_slack` slack bits (spare blocks = `s0 + 2 s1 + 4 s2 + …`).
- **Bit order:** bit `j` of an integer index = qubit `j` (`index_bits`). Qiskit prints qubit 0 **last**; `choice_shares` handles it via `int(key, 2)`.
- **QUBO storage:** `energy(y) = Σ Q[j,j] y_j + Σ_{j<k} Q[j,k] y_j y_k + offset`; lower triangle unused.
- **Fleet size** is never hard-coded in `src/`: functions take `plants` / `n_slack`, so the 10-plant stretch works by passing `--fleet 10` / `load_problem("10")`.

## Testing

```
pytest                 # all; TODO tests skip until implemented
pytest -m "not slow"   # skip the full-day QAOA run
pytest tests/test_qubo.py -v
```

`tests/test_qubo.py` checks `build_qubo` against the energy formula written out directly on **every** bitstring, so a wrong
expansion fails loudly. `test_milestone3_match_at_hour_12` is the milestone 3 "Match!" criterion.

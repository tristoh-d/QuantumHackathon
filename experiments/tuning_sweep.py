"""Milestone 4 tuning sweep: layers, penalty scale, warm start, slack bits (QAOA only).

    python -m experiments.tuning_sweep      # about 20 minutes

Compares QAOA settings against the un-tuned p=1 runs in results/shots_sweep*.csv:
more layers, the penalty weight A scaled against its default (2 * max c_i, which changes
hour to hour), warm start off (fresh angle search every hour), and 4 slack bits (10 plants).
Penalty scaling and warm start have no CLI flag, so this script wraps build_qubo and
run_qaoa. Writes results/tuning.csv (one row per day) and prints a summary.
"""
import csv
import time

import numpy as np

import src.quantum as quantum
import src.scheduler as scheduler
from src.classical import run_milp
from src.config import RESULTS_DIR, load_problem
from src.qubo import plant_hour_costs

_build_qubo = scheduler.build_qubo
_run_qaoa = quantum.run_qaoa
STATE = {"pen_scale": 1.0, "warm": True}


def build_qubo_scaled(plants, demand, reserve, was_on, penalty=None, n_slack=3):
    A = STATE["pen_scale"] * 2 * plant_hour_costs(plants, was_on).max()
    return _build_qubo(plants, demand, reserve, was_on, penalty=A, n_slack=n_slack)


def run_qaoa_maybe_cold(Q, offset, p=1, start=None, maxiter=60, **kwargs):
    return _run_qaoa(Q, offset, p=p, start=start if STATE["warm"] else None, maxiter=maxiter, **kwargs)


scheduler.build_qubo = build_qubo_scaled
quantum.run_qaoa = run_qaoa_maybe_cold

SEEDS = range(5)
CONFIGS = [
    # (fleet, name, p, pen_scale, warm, n_slack, shots)
    ("5", "p=2", 2, 1.0, True, 3, (5, 10, 20, 50)),
    ("5", "p=3", 3, 1.0, True, 3, (5, 10, 20, 50)),
    ("5", "penalty 0.5x", 1, 0.5, True, 3, (5, 10, 20, 50)),
    ("5", "penalty 3x", 1, 3.0, True, 3, (5, 10, 20, 50)),
    ("5", "no warm start", 1, 1.0, False, 3, (5, 10, 20, 50)),
    ("10", "p=2", 2, 1.0, True, 3, (200, 1000)),
    ("10", "4 slack bits", 1, 1.0, True, 4, (200, 1000)),
    ("10", "no warm start", 1, 1.0, False, 3, (200, 1000)),
]
FIELDS = ["fleet", "config", "p", "pen_scale", "warm", "n_slack", "shots", "seed", "valid", "total_cost",
          "gap_pct", "n_violations", "hours_matching_best", "mean_valid_share", "mean_p_best", "seconds"]

out = RESULTS_DIR / "tuning.csv"
RESULTS_DIR.mkdir(exist_ok=True)
rows = []
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    for fleet, name, p, pen, warm, n_slack, shot_list in CONFIGS:
        problem = load_problem(fleet)
        milp_cost = run_milp(problem)["cost"]
        STATE.update(pen_scale=pen, warm=warm)
        for shots in shot_list:
            for seed in SEEDS:
                r = scheduler.run_day(problem, milp_cost, sampler="qaoa", shots=shots, seed=seed, p=p,
                                      n_slack=n_slack)
                row = dict(fleet=fleet, config=name, p=p, pen_scale=pen, warm=warm, n_slack=n_slack,
                           shots=shots, seed=seed, valid=r["valid"], total_cost=round(r["total_cost"], 2),
                           gap_pct=round(r["gap_pct"], 4), n_violations=len(r["violations"]),
                           hours_matching_best=sum(h["matches_best"] for h in r["log"]),
                           mean_valid_share=round(float(np.mean([h["valid_share"] for h in r["log"]])), 4),
                           mean_p_best=round(float(np.mean([h["p_best"] for h in r["log"]])), 4),
                           seconds=round(r["seconds"], 2))
                w.writerow(row)
                f.flush()
                rows.append(row)
                print(f"[{time.strftime('%H:%M:%S')}] {fleet:>2} {name:<14} shots={shots:<5} seed={seed} "
                      f"valid={row['valid']!s:<5} gap={row['gap_pct']:+.2f}% {row['seconds']:.1f}s", flush=True)

print(f"\nsaved {out}\n")
print(f"{'fleet':<6}{'config':<15}{'shots':>6}{'valid':>8}{'mean gap':>10}{'valid share':>13}"
      f"{'p_best':>8}{'match':>7}{'sec':>7}")
keys = []
for r in rows:
    k = (r["fleet"], r["config"], r["shots"])
    if k not in keys:
        keys.append(k)
for k in keys:
    g = [r for r in rows if (r["fleet"], r["config"], r["shots"]) == k]
    gaps = [r["gap_pct"] for r in g if r["valid"]]
    gap = f"{np.mean(gaps):+.2f}%" if gaps else "-"
    print(f"{k[0]:<6}{k[1]:<15}{k[2]:>6}{len(gaps):>4} / {len(g):<1}{gap:>10}"
          f"{np.mean([r['mean_valid_share'] for r in g]):>13.3f}{np.mean([r['mean_p_best'] for r in g]):>8.4f}"
          f"{np.mean([r['hours_matching_best'] for r in g]):>7.1f}{np.mean([r['seconds'] for r in g]):>7.1f}")

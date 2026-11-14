"""Milestone 4 (required): QAOA vs random guessing across shots and seeds.

    python -m experiments.shots_sweep                       # shots 5,10,20,50,200 x 5 seeds, p=1
    python -m experiments.shots_sweep --samplers random     # quick, no qiskit needed
    python -m experiments.shots_sweep --p 2 --tag p2        # only AFTER you have explained the p=1 table

The README asks for this table BEFORE you tune layers, penalty weight or warm starts:
how many days come out valid, and the cost gap of the valid ones.

Writes one row per run to results/shots_sweep[_tag].csv and prints the summary table.
Interpreting it (which step of the loop is doing the work?) is yours to do.
"""
import argparse
import csv

import numpy as np

from experiments._common import todo_guard
from src.classical import run_milp
from src.config import N_SEEDS, N_SLACK, RESULTS_DIR, SHOT_GRID, load_problem
from src.scheduler import run_day

FIELDS = ["sampler", "shots", "seed", "p", "valid", "total_cost", "gap_pct", "n_violations",
          "hours_matching_best", "mean_valid_share", "mean_p_best", "seconds"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fleet", default="5", choices=["5", "10"])
    ap.add_argument("--samplers", nargs="+", default=["qaoa", "random"], choices=["qaoa", "random"])
    ap.add_argument("--shots", type=int, nargs="+", default=list(SHOT_GRID))
    ap.add_argument("--seeds", type=int, default=N_SEEDS, help="number of seeds (0..seeds-1)")
    ap.add_argument("--p", type=int, default=1)
    ap.add_argument("--penalty", type=float, default=None)
    ap.add_argument("--n-slack", type=int, default=N_SLACK)
    ap.add_argument("--tag", default="", help="suffix for the output file")
    args = ap.parse_args()

    problem = load_problem(args.fleet)
    milp_cost = run_milp(problem)["cost"]
    out = RESULTS_DIR / f"shots_sweep{'_' + args.tag if args.tag else ''}.csv"
    RESULTS_DIR.mkdir(exist_ok=True)
    rows = []
    with todo_guard("shots_sweep"), open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for sampler in args.samplers:
            for shots in args.shots:
                for seed in range(args.seeds):
                    r = run_day(problem, milp_cost, sampler=sampler, shots=shots, seed=seed, p=args.p,
                                penalty=args.penalty, n_slack=args.n_slack)
                    row = dict(sampler=sampler, shots=shots, seed=seed, p=args.p, valid=r["valid"],
                               total_cost=round(r["total_cost"], 2), gap_pct=round(r["gap_pct"], 4),
                               n_violations=len(r["violations"]),
                               hours_matching_best=sum(h["matches_best"] for h in r["log"]),
                               mean_valid_share=round(float(np.mean([h["valid_share"] for h in r["log"]])), 4),
                               mean_p_best=round(float(np.mean([h["p_best"] for h in r["log"]])), 4),
                               seconds=round(r["seconds"], 2))
                    w.writerow(row)
                    f.flush()
                    rows.append(row)
                    print(f"{sampler:>6} shots={shots:<4} seed={seed}  valid={row['valid']!s:<5} "
                          f"gap={row['gap_pct']:+.2f}%  {row['seconds']:.1f}s")

    print(f"\nsaved {out.relative_to(RESULTS_DIR.parent)}\n")
    print(f"{'sampler':<8}{'shots':>6}{'valid days':>12}{'mean gap (valid)':>18}{'min gap':>10}{'max gap':>10}")
    for sampler in args.samplers:
        for shots in args.shots:
            group = [r for r in rows if r["sampler"] == sampler and r["shots"] == shots]
            gaps = [r["gap_pct"] for r in group if r["valid"]]
            stats = (f"{np.mean(gaps):>+17.2f}%{min(gaps):>+9.2f}%{max(gaps):>+9.2f}%" if gaps
                     else f"{'-':>18}{'-':>10}{'-':>10}")
            print(f"{sampler:<8}{shots:>6}{len(gaps):>7} / {len(group):<3}{stats}")


if __name__ == "__main__":
    main()

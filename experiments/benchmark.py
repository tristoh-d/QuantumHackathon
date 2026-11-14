"""Compare every method on one fleet: MILP (optimal), cheapest-first rule, QAOA and random, hour by hour.

    python -m experiments.benchmark                 # 5 plants, QAOA p=1, 200 shots
    python -m experiments.benchmark --fleet 10      # stretch: 10 plants (check --n-slack first!)
    python -m experiments.benchmark --skip-qaoa     # classical + random only (no qiskit needed)

Writes results/benchmark_<fleet>.json. Methods whose TODOs are not filled in are reported as "TODO".
"""
import argparse

from experiments._common import save_json
from src.classical import run_milp, run_rule
from src.config import N_SLACK, load_problem
from src.scheduler import run_day


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fleet", default="5", choices=["5", "10"])
    ap.add_argument("--p", type=int, default=1, help="QAOA layers")
    ap.add_argument("--shots", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--penalty", type=float, default=None, help="QUBO penalty A (default 2 * max c_i)")
    ap.add_argument("--n-slack", type=int, default=N_SLACK)
    ap.add_argument("--skip-qaoa", action="store_true")
    ap.add_argument("--ramps", action="store_true", help="stretch goal: ramp limits in MILP and checker")
    args = ap.parse_args()

    problem = load_problem(args.fleet)
    milp = run_milp(problem, ramps=args.ramps)
    print(f"MILP: {problem.n} plants x {len(problem.demand)} hours, ${milp['cost']:,.0f} in {milp['seconds']:.3f} s")

    rows = {"MILP (optimal)": dict(total_cost=milp["cost"], gap_pct=0.0, violations=[], seconds=milp["seconds"],
                                   schedule=milp["schedule"])}
    day_kwargs = dict(p=args.p, shots=args.shots, seed=args.seed, penalty=args.penalty, n_slack=args.n_slack)
    jobs = [("cheapest-first rule", lambda: run_rule(problem, milp_cost=milp["cost"]))]
    if not args.skip_qaoa:
        jobs.append(("QAOA, hour by hour", lambda: run_day(problem, milp["cost"], sampler="qaoa", **day_kwargs)))
    jobs.append(("random, hour by hour", lambda: run_day(problem, milp["cost"], sampler="random", **day_kwargs)))

    for name, job in jobs:
        try:
            rows[name] = job()
        except NotImplementedError as e:
            rows[name] = None
            print(f"{name}: skipped ({e})")

    print(f"\n{'method':<26}{'daily cost $':>14}{'gap':>10}{'rules broken':>14}{'seconds':>10}")
    for name, r in rows.items():
        if r is None:
            print(f"{name:<26}{'TODO':>14}")
            continue
        secs = f"{r['seconds']:.2f}" if "seconds" in r else "-"
        print(f"{name:<26}{r['total_cost']:>14,.0f}{r['gap_pct']:>+9.2f}%{len(r['violations']):>14}{secs:>10}")

    save_json(f"benchmark_{args.fleet}.json", {
        "args": vars(args),
        "methods": {name: None if r is None else {k: r.get(k) for k in
                                                  ("total_cost", "gap_pct", "violations", "seconds", "schedule")}
                    for name, r in rows.items()},
    })


if __name__ == "__main__":
    main()

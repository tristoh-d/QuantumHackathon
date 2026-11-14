"""Compare every method on one fleet: MILP (optimal), cheapest-first rule, QAOA and random, hour by hour.

    python -m experiments.benchmark                 # 5 plants, QAOA p=1, 200 shots
    python -m experiments.benchmark --fleet 10      # stretch: 10 plants (check --n-slack first!)
    python -m experiments.benchmark --skip-qaoa     # classical + random only (no qiskit needed)
    python -m experiments.benchmark --fleet tva --day peak              # real TVA fleet, one day
    python -m experiments.benchmark --fleet tva --day sample:summer:weekday:3
    python -m experiments.benchmark --fleet tva --all-days              # every saved TVA day (MILP + rule)

Writes results/benchmark_<fleet>.json (results/benchmark_tva_all.json for --all-days). Methods whose
TODOs are not filled in are reported as "TODO". QAOA and random are skipped when the fleet needs more
than MAX_LOCAL_QUBITS qubits (the TVA fleet needs 25).
"""
import argparse

from experiments._common import save_json
from src.check import check_schedule
from src.classical import run_milp, run_rule
from src.config import FLEETS, MAX_LOCAL_QUBITS, load_problem, tva_day_names
from src.scheduler import run_day

KEEP = ("total_cost", "gap_pct", "violations", "seconds", "schedule")


def run_quantum(problem, milp_cost, sampler, **day_kwargs):
    """run_day on the fleet's block view, scored by the checker on the real problem."""
    result = run_day(problem.block_view(), milp_cost, sampler=sampler, **day_kwargs)
    scored = check_schedule(problem.plants, problem.demand, problem.reserve, result["schedule"],
                            milp_cost=milp_cost, verbose=False)
    scored.update(schedule=result["schedule"], seconds=result["seconds"])
    return scored


def benchmark(problem, args):
    milp = run_milp(problem, ramps=args.ramps)
    label = f" ({problem.day})" if problem.day else ""
    print(f"MILP{label}: {problem.n} plants x {len(problem.demand)} hours, "
          f"${milp['cost']:,.0f} in {milp['seconds']:.3f} s")

    rows = {"MILP (optimal)": dict(total_cost=milp["cost"], gap_pct=0.0, violations=[], seconds=milp["seconds"],
                                   schedule=milp["schedule"])}
    n_slack = problem.n_slack if args.n_slack is None else args.n_slack
    day_kwargs = dict(p=args.p, shots=args.shots, seed=args.seed, penalty=args.penalty, n_slack=n_slack)
    jobs = [("cheapest-first rule", lambda: run_rule(problem, milp_cost=milp["cost"]))]
    quantum = not args.all_days
    if quantum and problem.n + n_slack > MAX_LOCAL_QUBITS:
        print(f"QAOA / random: skipped ({problem.n + n_slack} qubits > MAX_LOCAL_QUBITS = {MAX_LOCAL_QUBITS})")
        quantum = False
    if quantum and not args.skip_qaoa:
        jobs.append(("QAOA, hour by hour", lambda: run_quantum(problem, milp["cost"], "qaoa", **day_kwargs)))
    if quantum:
        jobs.append(("random, hour by hour", lambda: run_quantum(problem, milp["cost"], "random", **day_kwargs)))

    for name, job in jobs:
        try:
            rows[name] = job()
        except NotImplementedError as e:
            rows[name] = None
            print(f"{name}: skipped ({e})")
    return rows


def print_table(rows):
    print(f"\n{'method':<26}{'daily cost $':>14}{'gap':>10}{'rules broken':>14}{'seconds':>10}")
    for name, r in rows.items():
        if r is None:
            print(f"{name:<26}{'TODO':>14}")
            continue
        secs = f"{r['seconds']:.2f}" if "seconds" in r else "-"
        print(f"{name:<26}{r['total_cost']:>14,.0f}{r['gap_pct']:>+9.2f}%{len(r['violations']):>14}{secs:>10}")


def summarize(rows):
    return {name: None if r is None else {k: r.get(k) for k in KEEP} for name, r in rows.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fleet", default="5", choices=list(FLEETS))
    ap.add_argument("--day", default=None, help="TVA fleet: saved day name, ISO date, or sample:<season>:<daytype>:<seed>")
    ap.add_argument("--all-days", action="store_true", help="TVA fleet: MILP + rule on every saved day")
    ap.add_argument("--p", type=int, default=1, help="QAOA layers")
    ap.add_argument("--shots", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--penalty", type=float, default=None, help="QUBO penalty A (default 2 * max c_i)")
    ap.add_argument("--n-slack", type=int, default=None, help="QUBO slack bits (default: the fleet's)")
    ap.add_argument("--skip-qaoa", action="store_true")
    ap.add_argument("--ramps", action="store_true", help="stretch goal: ramp limits in MILP and checker")
    args = ap.parse_args()
    if (args.day or args.all_days) and args.fleet != "tva":
        ap.error("--day and --all-days need --fleet tva")

    if args.all_days:
        days = {}
        for name in tva_day_names():
            rows = benchmark(load_problem("tva", day=name), args)
            days[name] = summarize(rows)
            rule = rows["cheapest-first rule"]
            if rule is not None:
                print(f"    rule gap {rule['gap_pct']:+.2f}%, {len(rule['violations'])} rules broken")
        gaps = [d["cheapest-first rule"]["gap_pct"] for d in days.values() if d["cheapest-first rule"]]
        if gaps:
            print(f"\n{len(days)} days: rule gap mean {sum(gaps) / len(gaps):+.2f}%, "
                  f"min {min(gaps):+.2f}%, max {max(gaps):+.2f}%")
        save_json("benchmark_tva_all.json", {"args": vars(args), "days": days})
        return

    problem = load_problem(args.fleet, day=args.day)
    rows = benchmark(problem, args)
    print_table(rows)
    save_json(f"benchmark_{args.fleet}.json", {"args": vars(args), "day": problem.day, "methods": summarize(rows)})


if __name__ == "__main__":
    main()

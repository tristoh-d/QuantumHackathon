"""Milestone 3: does the QUBO's cheapest bitstring pick the best on/off choice?

    python -m experiments.hour_check                    # hour 12 in detail + all 24 hours
    python -m experiments.hour_check --hour 15
    python -m experiments.hour_check --was-on milp      # previous hour taken from the MILP (default)
    python -m experiments.hour_check --was-on start     # previous hour = midnight state, for every hour

"Match!" checks one hour given the hour before; it does not prove a good full day.
Stretch goal ("a better hour cost"): use --was-on start and --fleet 10 to find cases where
the TODO 2 approximation picks the wrong plants, then explain why.
"""
import argparse

from experiments._common import todo_guard
from src.check import check_hour
from src.classical import run_milp
from src.config import N_SLACK, load_problem
from src.qubo import brute_force_qubo, build_qubo, label


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fleet", default="5", choices=["5", "10"])
    ap.add_argument("--hour", type=int, default=12)
    ap.add_argument("--was-on", default="milp", choices=["milp", "start"])
    ap.add_argument("--penalty", type=float, default=None)
    ap.add_argument("--n-slack", type=int, default=N_SLACK)
    args = ap.parse_args()

    problem = load_problem(args.fleet)
    milp_schedule = run_milp(problem)["schedule"]

    def prev(t):
        if args.was_on == "start" or t == 0:
            return problem.start_state
        return list(milp_schedule[t - 1])

    with todo_guard("hour_check"):
        t = args.hour
        Q, offset = build_qubo(problem.plants, problem.demand[t], problem.reserve[t], prev(t),
                               penalty=args.penalty, n_slack=args.n_slack)
        bits, energy = brute_force_qubo(Q, offset)
        n = problem.n
        print(f"Hour {t}: cheapest QUBO bitstring: plants {bits[:n]}, slack {bits[n:]}, energy {energy:,.0f}")
        check_hour(problem.plants, problem.demand[t], problem.reserve[t], bits[:n], was_on=prev(t))
        print(f"(The MILP picked {label(list(milp_schedule[t]), problem.names)} for this hour.)\n")

        print(f"{'hour':>4} {'demand':>7}  {'QUBO pick':<32}{'match':>6}")
        matches = 0
        for t in problem.hours:
            Qt, off_t = build_qubo(problem.plants, problem.demand[t], problem.reserve[t], prev(t),
                                   penalty=args.penalty, n_slack=args.n_slack)
            bits_t, _ = brute_force_qubo(Qt, off_t)
            ok = check_hour(problem.plants, problem.demand[t], problem.reserve[t], bits_t[:n], was_on=prev(t),
                            verbose=False)["matches_best"]
            matches += ok
            print(f"{t:>4} {problem.demand[t]:>7.0f}  {label(list(bits_t[:n]), problem.names):<32}"
                  f"{'yes' if ok else 'NO':>6}")
        print(f"\nYour QUBO's cheapest answer matches the brute-force best in {matches} of {len(problem.hours)} hours.")


if __name__ == "__main__":
    main()

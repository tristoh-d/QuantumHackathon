"""Benchmarks on real TVA demand days (EIA-930), bootstrapped by season x weekday/weekend.

    python -m experiments.tva_benchmark classical               # 20-plant TVA fleet: MILP vs rule, 30 days/stratum
    python -m experiments.tva_benchmark quantum                 # TVA day shapes on the 5-plant fleet: + QAOA, random
    python -m experiments.tva_benchmark quantum --shots 20 200 --days 5
    python -m experiments.tva_benchmark quantum --fleet 10 --shots 200 1000   # same days, 10-plant fleet

classical: the real TVA thermal fleet (plants_tva.csv) on bootstrapped net-load days. QAOA is not run
           here: the fleet needs 25 qubits, more than MAX_LOCAL_QUBITS.
quantum:   the same kind of days, rescaled (src.demand sample_days scale_to) so the TVA fleet's capacity
           maps to the small fleet's (5 plants: 850 MW, 8 qubits; 10 plants: 1,500 MW, 13 qubits).
           This tests QAOA on many real load shapes instead of one. The same seed gives the same
           dates for both fleets.

Writes one row per day (and sampler/shots) to results/tva_classical.csv or tva_quantum<fleet>.csv and prints markdown summary
tables (the ones in docs/results.md). Days are drawn without replacement; seed = --seed + stratum index.
"""
import argparse
import csv
from dataclasses import replace

import numpy as np

from experiments._common import todo_guard
from src.classical import run_milp, run_rule
from src.config import RESULTS_DIR, load_problem
from src import demand as tva
from src.scheduler import run_day

STRATA = [(s, t) for s in tva.SEASON_ORDER for t in tva.DAYTYPES]


def days_for(stratum_index, season, daytype, n, seed, scale_to=None):
    return tva.sample_days(season, daytype, n=n, seed=seed + stratum_index, replace=False, scale_to=scale_to)


def with_day(problem, day):
    return replace(problem, demand=day.demand.astype(float), reserve=day.reserve.astype(float), day=day.date)


def boot_ci(x, reps=2000):
    """95% bootstrap confidence interval of the mean."""
    x = np.asarray(x, dtype=float)
    means = [np.random.default_rng(i).choice(x, len(x)).mean() for i in range(reps)]
    return np.percentile(means, [2.5, 97.5])


def write_csv(name, rows):
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / name
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"saved {path.relative_to(RESULTS_DIR.parent)}")


# ---------------------------------------------------------------- classical
def classical(args):
    base = load_problem("tva")
    rows = []
    for k, (season, daytype) in enumerate(STRATA):
        for day in days_for(k, season, daytype, args.days, args.seed):
            p = with_day(base, day)
            milp = run_milp(p)
            rule = run_rule(p, milp_cost=milp["cost"])
            rows.append(dict(season=season, daytype=daytype, date=day.date, peak_mw=day.demand.max(),
                             min_mw=day.demand.min(), milp_cost=round(milp["cost"]), milp_seconds=round(milp["seconds"], 3),
                             rule_cost=round(rule["total_cost"]), rule_gap_pct=round(rule["gap_pct"], 3),
                             rule_violations=len(rule["violations"])))
        print(f"  {season} {daytype}: done")
    write_csv("tva_classical.csv", rows)

    print("\n| Season | Day type | Days | Rule gap mean [95% CI] | Median | Worst | Days with broken rules | MILP time avg / max |")
    print("|---|---|---|---|---|---|---|---|")
    for season, daytype in STRATA:
        r = [x for x in rows if x["season"] == season and x["daytype"] == daytype]
        g = np.array([x["rule_gap_pct"] for x in r])
        lo, hi = boot_ci(g)
        broken = np.mean([x["rule_violations"] > 0 for x in r])
        secs = [x["milp_seconds"] for x in r]
        print(f"| {season} | {daytype} | {len(r)} | {g.mean():+.2f}% [{lo:+.2f}, {hi:+.2f}] | {np.median(g):+.2f}% "
              f"| {g.max():+.2f}% | {broken:.0%} | {np.mean(secs):.2f} / {max(secs):.2f} s |")
    g = np.array([x["rule_gap_pct"] for x in rows])
    lo, hi = boot_ci(g)
    peak = np.array([x["peak_mw"] for x in rows]); low = np.array([x["min_mw"] for x in rows])
    print(f"| **all** | | {len(rows)} | **{g.mean():+.2f}%** [{lo:+.2f}, {hi:+.2f}] | {np.median(g):+.2f}% | {g.max():+.2f}% "
          f"| {np.mean([x['rule_violations'] > 0 for x in rows]):.0%} | {np.mean([x['milp_seconds'] for x in rows]):.2f} / "
          f"{max(x['milp_seconds'] for x in rows):.2f} s |")
    print(f"\ncorrelation of rule gap with: daily peak {np.corrcoef(peak, g)[0, 1]:+.2f}, daily minimum "
          f"{np.corrcoef(low, g)[0, 1]:+.2f}, peak/min ratio {np.corrcoef(peak / low, g)[0, 1]:+.2f}")


# ---------------------------------------------------------------- quantum
def quantum(args):
    base = load_problem(args.fleet)
    cap = sum(p["pmax_mw"] for p in base.plants)
    rows = []
    for k, (season, daytype) in enumerate(STRATA):
        for day in days_for(k, season, daytype, args.days, args.seed, scale_to=cap):
            p = with_day(base, day)
            milp = run_milp(p)
            rule = run_rule(p, milp_cost=milp["cost"])
            common = dict(season=season, daytype=daytype, date=day.date, peak_mw=day.demand.max(),
                          min_mw=day.demand.min(), milp_cost=round(milp["cost"]))
            rows.append(dict(common, method="rule", shots="", valid=int(not rule["violations"]),
                             cost=round(rule["total_cost"]), gap_pct=round(rule["gap_pct"], 3),
                             violations=len(rule["violations"]), hours_matching_best="", seconds=""))
            for shots in args.shots:
                for sampler in args.samplers:
                    with todo_guard(f"{sampler} day"):
                        r = run_day(p, milp["cost"], sampler=sampler, shots=shots, seed=args.qseed, p=args.p)
                    rows.append(dict(common, method=sampler, shots=shots, valid=int(not r["violations"]),
                                     cost=round(r["total_cost"]), gap_pct=round(r["gap_pct"], 3),
                                     violations=len(r["violations"]),
                                     hours_matching_best=sum(h["matches_best"] for h in r["log"]),
                                     seconds=round(r["seconds"], 2)))
        print(f"  {season} {daytype}: done")
    write_csv(f"tva_quantum{args.fleet}.csv", rows)

    n_days = len(rows) // (1 + len(args.shots) * len(args.samplers))
    print(f"\n{n_days} TVA days scaled to the {args.fleet}-plant fleet, p={args.p}, sampler seed {args.qseed}:\n")
    print("| Method | Shots | Valid days | Gap, all days (mean [95% CI]) | Gap, valid days | Hours matching best (of 24) | Time per day |")
    print("|---|---|---|---|---|---|---|")
    keys = [("rule", "")] + [(s, n) for n in args.shots for s in args.samplers]
    for method, shots in keys:
        r = [x for x in rows if x["method"] == method and x["shots"] == shots]
        g = np.array([x["gap_pct"] for x in r])
        lo, hi = boot_ci(g)
        gv = [x["gap_pct"] for x in r if x["valid"]]
        valid_gap = f"{np.mean(gv):+.2f}%" if gv else "—"
        match = f"{np.mean([x['hours_matching_best'] for x in r]):.1f}" if method != "rule" else "—"
        secs = f"{np.mean([x['seconds'] for x in r]):.1f} s" if method != "rule" else "—"
        name = {"rule": "Cheapest-first rule", "qaoa": f"QAOA p={args.p}", "random": "Random"}[method]
        print(f"| {name} | {shots or '—'} | {sum(x['valid'] for x in r)} / {len(r)} | {g.mean():+.2f}% [{lo:+.2f}, {hi:+.2f}] "
              f"| {valid_gap} | {match} | {secs} |")

    if "qaoa" in args.samplers and "random" in args.samplers:
        print()
        for shots in args.shots:
            q = {x["date"]: x for x in rows if x["method"] == "qaoa" and x["shots"] == shots}
            rd = {x["date"]: x for x in rows if x["method"] == "random" and x["shots"] == shots}
            both = [d for d in q if q[d]["valid"] and rd[d]["valid"]]
            diff = np.array([q[d]["gap_pct"] - rd[d]["gap_pct"] for d in both])
            if len(diff):
                print(f"{shots} shots, days valid for both ({len(both)}): QAOA cheaper on {np.sum(diff < -1e-9)}, "
                      f"tie on {np.sum(np.abs(diff) <= 1e-9)}, random cheaper on {np.sum(diff > 1e-9)}; "
                      f"mean QAOA - random gap {diff.mean():+.2f} points")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("part", choices=["classical", "quantum"])
    ap.add_argument("--days", type=int, default=None, help="days per stratum (default 30 classical, 5 quantum)")
    ap.add_argument("--seed", type=int, default=11, help="day-sampling seed")
    ap.add_argument("--shots", type=int, nargs="+", default=[20, 200])
    ap.add_argument("--samplers", nargs="+", default=["qaoa", "random"], choices=["qaoa", "random"])
    ap.add_argument("--fleet", default="5", choices=["5", "10"], help="quantum part: small fleet to scale days to")
    ap.add_argument("--p", type=int, default=1)
    ap.add_argument("--qseed", type=int, default=7, help="sampler seed")
    args = ap.parse_args()
    if args.days is None:
        args.days = 30 if args.part == "classical" else 5
    {"classical": classical, "quantum": quantum}[args.part](args)


if __name__ == "__main__":
    main()

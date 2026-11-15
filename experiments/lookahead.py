"""Hybrid QAOA + classical look-ahead on real TVA load shapes (src/lookahead.py).

    python -m experiments.lookahead run --fleet 5                    # 40 TVA days, ~15 min on 8 cores
    python -m experiments.lookahead run --fleet 10 --shots 200 1000 --horizons 4
    python -m experiments.lookahead summary --fleet 5                # tables from the saved CSV

Same days as `python -m experiments.tva_benchmark quantum` (5 per season x day type, day seed 11),
scaled so the TVA fleet's 17,735 MW maps to the small fleet's capacity. Every day is scored by the
organizers' checker against its own MILP.

Methods (H = look-ahead hours; H=0 is the existing hour-by-hour loop):
    greedy-qaoa, greedy-random   QAOA / random samples, keep the cheapest this hour       (H=0)
    la-qaoa                      QAOA samples, keep the best over this hour + next H hours
    la-qaoa-shaped               same, and the QUBO's plant costs come from the look-ahead
    la-random                    random samples + look-ahead (the honesty check)
    la-all                       every on/off choice + look-ahead (no sampling: the ceiling for H)

Writes results/lookahead_fleet<fleet>.csv, one row per day x method x H x shots.
"""
import argparse
import csv
import os
import time
from multiprocessing import Pool

import numpy as np

from experiments.tva_benchmark import STRATA, boot_ci, days_for, with_day
from src.classical import run_milp, run_rule
from src.config import RESULTS_DIR, load_problem
from src.scheduler import run_day

NAMES = {"greedy-qaoa": "QAOA, hour by hour", "greedy-random": "Random, hour by hour",
         "la-qaoa": "QAOA + look-ahead", "la-qaoa-shaped": "QAOA (shaped QUBO) + look-ahead",
         "la-random": "Random + look-ahead", "la-all": "All choices + look-ahead"}
METHOD_ORDER = list(NAMES)


def configs(args):
    out = []
    for shots in args.shots:
        out += [("greedy-qaoa", 0, shots), ("greedy-random", 0, shots)]
        for H in args.horizons:
            out += [("la-qaoa", H, shots), ("la-qaoa-shaped", H, shots), ("la-random", H, shots)]
    out += [("la-all", H, "") for H in args.all_horizons]
    return out


def run_one_day(job):
    """All methods on one TVA day. Runs in a worker process."""
    fleet, (k, season, daytype, day), cfgs, qseed, p_layers, max_candidates = job
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    prob = with_day(load_problem(fleet), day)
    milp = run_milp(prob)
    rule = run_rule(prob, milp_cost=milp["cost"])
    common = dict(season=season, daytype=daytype, date=day.date, peak_mw=day.demand.max(),
                  min_mw=day.demand.min(), milp_cost=round(milp["cost"], 2))
    rows = [dict(common, method="rule", horizon="", shots="", valid=int(not rule["violations"]),
                 cost=round(rule["total_cost"], 2), gap_pct=round(rule["gap_pct"], 4),
                 violations=len(rule["violations"]), seconds="", lookahead_solves="", mean_candidates="")]
    for method, H, shots in cfgs:
        sampler = "qaoa" if "qaoa" in method else method.split("-")[-1]
        r = run_day(prob, milp["cost"], sampler=sampler, shots=shots or 1, seed=qseed, p=p_layers,
                    lookahead=H, shape_qubo=(method == "la-qaoa-shaped"),
                    max_candidates=max_candidates if sampler != "all" else None)
        rows.append(dict(common, method=method, horizon=H, shots=shots, valid=int(not r["violations"]),
                         cost=round(r["total_cost"], 2), gap_pct=round(r["gap_pct"], 4),
                         violations=len(r["violations"]), seconds=round(r["seconds"], 2),
                         lookahead_solves=r["log"][-1]["lookahead_solves"],
                         mean_candidates=round(np.mean([h["n_candidates"] for h in r["log"]]), 2)))
    return rows


def run(args):
    """Runs every day not already in the CSV. Each finished day is appended at once, so a stopped
    run resumes where it left off (delete the CSV to start over)."""
    base = load_problem(args.fleet)
    cap = sum(p["pmax_mw"] for p in base.plants)
    days = [(k, s, d, day) for k, (s, d) in enumerate(STRATA)
            for day in days_for(k, s, d, args.days, args.seed, scale_to=cap)]
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"lookahead_fleet{args.fleet}.csv"
    done = {r["date"] for r in load_rows(args.fleet)} if path.exists() else set()
    todo = [d for d in days if d[3].date not in done]
    cfgs = configs(args)
    jobs = [(args.fleet, d, cfgs, args.qseed, args.p, args.max_candidates) for d in todo]
    print(f"{len(days)} days ({len(done)} already in {path.name}), {len(cfgs)} configs, {args.workers} workers")
    start = time.perf_counter()
    with Pool(args.workers, maxtasksperchild=1) as pool:
        for i, day_rows in enumerate(pool.imap_unordered(run_one_day, jobs), 1):
            new = not path.exists()
            with open(path, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(day_rows[0]))
                if new:
                    w.writeheader()
                w.writerows(day_rows)
            print(f"  {i}/{len(todo)} days ({time.perf_counter() - start:.0f} s)", flush=True)
    print(f"saved {path.relative_to(RESULTS_DIR.parent)}")
    print()
    summary(args)


def load_rows(fleet):
    with open(RESULTS_DIR / f"lookahead_fleet{fleet}.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("valid", "violations"):
            r[k] = int(r[k])
        for k in ("cost", "gap_pct", "milp_cost"):
            r[k] = float(r[k])
    return rows


def summary(args):
    rows = load_rows(args.fleet)
    n_days = len({r["date"] for r in rows})
    print(f"{n_days} TVA days scaled to the {args.fleet}-plant fleet:\n")
    print("| Method | H | Shots | Valid days | Gap, all days (mean [95% CI]) | Median | Days at the optimum | "
          "Time per day | Look-ahead MILPs per day | Candidates per hour |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    keys = sorted({(r["method"], r["horizon"], r["shots"]) for r in rows},
                  key=lambda k: (k[0] != "rule", k[2] == "", int(k[2] or 0), METHOD_ORDER.index(k[0])
                                 if k[0] in METHOD_ORDER else -1, int(k[1] or 0)))
    for method, H, shots in keys:
        r = [x for x in rows if (x["method"], x["horizon"], x["shots"]) == (method, H, shots)]
        g = np.array([x["gap_pct"] for x in r])
        lo, hi = boot_ci(g)
        opt = sum(abs(x) < 0.01 for x in g)
        name = NAMES.get(method, "Cheapest-first rule")
        if method == "rule":
            print(f"| {name} | — | — | {sum(x['valid'] for x in r)} / {len(r)} | {g.mean():+.2f}% [{lo:+.2f}, {hi:+.2f}] "
                  f"| {np.median(g):+.2f}% | {opt} | — | — | — |")
            continue
        secs = np.mean([float(x["seconds"]) for x in r])
        solves = np.mean([float(x["lookahead_solves"]) for x in r])
        cands = np.mean([float(x["mean_candidates"]) for x in r])
        print(f"| {name} | {H} | {shots or '—'} | {sum(x['valid'] for x in r)} / {len(r)} | {g.mean():+.2f}% "
              f"[{lo:+.2f}, {hi:+.2f}] | {np.median(g):+.2f}% | {opt} | {secs:.1f} s | {solves:.0f} | {cands:.1f} |")

    def paired(a, b, label):
        A = {x["date"]: x for x in rows if (x["method"], x["horizon"], x["shots"]) == a}
        B = {x["date"]: x for x in rows if (x["method"], x["horizon"], x["shots"]) == b}
        both = [d for d in A if d in B and A[d]["valid"] and B[d]["valid"]]
        if not both:
            return
        diff = np.array([A[d]["gap_pct"] - B[d]["gap_pct"] for d in both])
        print(f"- {label}: {len(both)} days valid for both; first cheaper on {np.sum(diff < -1e-6)}, "
              f"tie on {np.sum(np.abs(diff) <= 1e-6)}, second cheaper on {np.sum(diff > 1e-6)}; "
              f"mean difference {diff.mean():+.2f} points")

    print("\nPaired, same day (first minus second):")
    shots_list = sorted({r["shots"] for r in rows if r["shots"]}, key=int)
    horizons = sorted({r["horizon"] for r in rows if r["method"] == "la-qaoa"}, key=int)
    for s in shots_list:
        for H in horizons:
            paired(("la-qaoa", H, s), ("greedy-qaoa", "0", s), f"{s} shots, H={H}: QAOA + look-ahead vs QAOA hour by hour")
            paired(("la-qaoa-shaped", H, s), ("la-qaoa", H, s), f"{s} shots, H={H}: shaped vs plain QUBO")
            paired(("la-qaoa-shaped", H, s), ("la-random", H, s), f"{s} shots, H={H}: QAOA (shaped) vs random, both + look-ahead")
            paired(("la-qaoa", H, s), ("la-random", H, s), f"{s} shots, H={H}: QAOA (plain) vs random, both + look-ahead")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("part", choices=["run", "summary"])
    ap.add_argument("--fleet", default="5", choices=["5", "10"])
    ap.add_argument("--days", type=int, default=5, help="days per season x day type")
    ap.add_argument("--seed", type=int, default=11, help="day-sampling seed (same as tva_benchmark)")
    ap.add_argument("--qseed", type=int, default=7, help="sampler seed")
    ap.add_argument("--shots", type=int, nargs="+", default=[10, 20, 50])
    ap.add_argument("--horizons", type=int, nargs="+", default=[1, 4], help="H for the sampled methods")
    ap.add_argument("--all-horizons", type=int, nargs="+", default=[1, 2, 4, 8, 23], help="H for la-all")
    ap.add_argument("--max-candidates", type=int, default=None, help="look-ahead scores only the K most-sampled")
    ap.add_argument("--p", type=int, default=1)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()
    {"run": run, "summary": summary}[args.part](args)


if __name__ == "__main__":
    main()

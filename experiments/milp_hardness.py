"""Where MILP struggles, and how exact (noise-free) QAOA, simulated annealing and random guessing do there.

    python -m experiments.milp_hardness milp                         # MILP-only scaling, n up to 50
    python -m experiments.milp_hardness quantum --family interaction # exact QAOA p=1..3 + SA + random, n <= 22
    python -m experiments.milp_hardness quantum --sizes 8 10         # quick check
    python -m experiments.milp_hardness gpu                          # plan the qBraid gpu-sv jobs (prints only)
    python -m experiments.milp_hardness gpu --submit                 # submit them (uses the .env API key)
    python -m experiments.milp_hardness gpu-fetch                    # collect finished gpu-sv jobs
    python -m experiments.milp_hardness summary                      # markdown tables for docs/results.md

Scenario families: src/hard_instances.py (market_split, interaction, symmetric). Research note: docs/milp_hard_cases.md.

Every quantum number here is exact and noise-free: QAOA probabilities come from the full statevector
(src/exact_qaoa.py), so p_opt is the true chance that one shot returns an optimal schedule, not a
shot estimate. gpu-sv is also noise-free but returns shot counts; those rows say so.

Outputs (results/ is git-ignored): hardness_milp.csv, hardness_quantum_<family>.csv, hardness_gpu.csv.
"""
import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np

from src import anneal, exact_qaoa as eq, hard_instances as hi, hard_milp
from src.config import RESULTS_DIR

SEEDS = range(5)
QUANTUM_SIZES = (8, 10, 12, 14, 16, 18, 20, 22)
MILP_SIZES = (10, 15, 20, 25, 30, 35, 40, 45, 50)
GPU_SIZES = (24, 28)
GPU_SHOTS = 10_000
SA_RUNS, SA_SWEEPS = 1000, 1000


def append_row(path, row):
    path.parent.mkdir(exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def read_rows(path):
    if not Path(path).exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def angles_str(a):
    return ";".join(f"{v:.6f}" for v in a)


def parse_angles(s):
    return np.array([float(v) for v in s.split(";")])


# ---------------------------------------------------------------- MILP scaling
def cmd_milp(args):
    path = RESULTS_DIR / "hardness_milp.csv"
    done = {(r["family"], r["n"], r["seed"]) for r in read_rows(path)}
    for fam in args.family:
        for n in args.sizes:
            for seed in SEEDS:
                if (fam, str(n), str(seed)) in done:
                    continue
                inst = hi.make(fam, n, seed)
                r = hard_milp.solve(inst, time_limit=args.time_limit)
                row = dict(family=fam, n=n, seed=seed, m=inst.meta.get("m", ""), milp_vars=len(inst.c),
                           milp_rows=inst.A.shape[0], cost=r["cost"], seconds=round(r["seconds"], 4),
                           nodes=r["nodes"], gap=r["gap"], timeout=r["timeout"])
                append_row(path, row)
                note = ""
                if r["timeout"]:
                    note = "  TIMEOUT, no schedule found" if r["gap"] is None else f"  TIMEOUT gap={r['gap']:.3f}"
                print(f"{fam:13s} n={n:3d} seed={seed}  {r['seconds']:7.2f} s  {r['nodes']:>9d} nodes{note}",
                      flush=True)


# ---------------------------------------------------------------- exact quantum + SA + random
def feasible_mask(inst):
    """Feasible bitstrings = zero penalty energy (penalty-only QUBO with weight 1)."""
    Qp, off = hi.penalty_qubo(np.zeros(inst.n), inst.meta["eq_rows"], inst.meta["eq_rhs"], 1.0)
    return np.isclose(eq.energies(Qp, off), 0.0)


def cmd_quantum(args):
    for fam in args.family:
        path = RESULTS_DIR / f"hardness_quantum_{fam}.csv"
        done = {(r["n"], r["seed"], r["method"]) for r in read_rows(path)}
        tuned = {}                                     # (n, p) -> list of tuned angles, for transfer checks
        for r in read_rows(path):
            if r["method"].startswith("qaoa_p") and not r["method"].endswith("transfer"):
                tuned.setdefault((int(r["n"]), int(r["method"][6])), []).append(parse_angles(r["angles"]))
        for n in args.sizes:
            for seed in SEEDS:
                if (str(n), str(seed), "sa") in done:
                    continue
                inst = hi.make(fam, n, seed)
                milp = hard_milp.solve(inst, time_limit=120)
                t0 = time.perf_counter()
                P = eq.Problem(inst.Q, inst.offset)
                build_s = time.perf_counter() - t0
                feas = feasible_mask(inst)
                n_opt = int(P.opt_mask.sum())
                assert milp["cost"] is not None and abs(milp["cost"] - P.e_min) < 1e-6, (fam, n, seed)
                base = dict(family=fam, n=n, seed=seed, e_min=P.e_min, milp_cost=milp["cost"],
                            milp_seconds=round(milp["seconds"], 4), milp_nodes=milp["nodes"], n_opt=n_opt,
                            n_feasible=int(feas.sum()), brute_force_seconds=round(build_s, 3))

                def emit(method, p_success, p_feasible, mean_norm, seconds, unit, angles=""):
                    row = dict(base, method=method, p_success=p_success, p_feasible=p_feasible,
                               mean_norm=mean_norm, tts99=eq.tts99(p_success), tts_unit=unit,
                               seconds=round(seconds, 4), angles=angles)
                    append_row(path, row)
                    print(f"{fam:13s} n={n:2d} s={seed} {method:16s} p_opt={p_success:.3e} "
                          f"p_feas={p_feasible:.3f} norm={mean_norm:.3f} t={seconds:.1f}s", flush=True)

                emit("random", n_opt / 2 ** n, feas.mean(), float(P.E_norm.mean()), 0.0, "shots")
                prev = None
                for p in args.p:
                    angles, secs = eq.tune(P, p, start=prev)
                    st = P.stats(angles, feas)
                    emit(f"qaoa_p{p}", st["p_opt"], st["p_feasible"], st["mean_norm"], secs, "shots",
                         angles_str(angles))
                    tuned.setdefault((n, p), []).append(angles)
                    prev = angles
                    smaller = [m for (m, q) in tuned if q == p and m < n]
                    if smaller:                         # angles from the next smaller size, no tuning here
                        src = np.median(np.array(tuned[(max(smaller), p)]), axis=0)
                        st = P.stats(src, feas)
                        emit(f"qaoa_p{p}_transfer", st["p_opt"], st["p_feasible"], st["mean_norm"], 0.0,
                             "shots", angles_str(src))
                x, E, s_run = anneal.anneal(inst.Q, inst.offset, runs=SA_RUNS, sweeps=SA_SWEEPS, seed=seed,
                                            energy_unit=1.0)
                ok = np.isclose(E, P.e_min, atol=1e-6)
                feas_runs = np.mean([inst.feasible(r) for r in x])
                norm = float(np.mean((E - P.e_min) / (P.e_max - P.e_min)))
                emit("sa", float(ok.mean()), float(feas_runs), norm, s_run * SA_RUNS, f"runs of {SA_SWEEPS} sweeps")
                del P


# ---------------------------------------------------------------- qBraid gpu-sv (noise-free, shot counts)
def transfer_angles(fam, p):
    rows = [r for r in read_rows(RESULTS_DIR / f"hardness_quantum_{fam}.csv") if r["method"] == f"qaoa_p{p}"]
    if not rows:
        raise SystemExit(f"no tuned p={p} angles for {fam}: run `quantum --family {fam}` first")
    n_max = max(int(r["n"]) for r in rows)
    return n_max, np.median([parse_angles(r["angles"]) for r in rows if int(r["n"]) == n_max], axis=0)


def gpu_jobs(args):
    jobs = []
    for fam in args.family:
        n_src, angles = transfer_angles(fam, args.gpu_p)
        for n in args.gpu_sizes:
            for seed in range(args.gpu_seeds):
                jobs.append(dict(family=fam, n=n, seed=seed, p=args.gpu_p, angles_from_n=n_src, angles=angles))
    return jobs


def cmd_gpu(args):
    from src.config import DEVICES
    from src.hardware import build_hardware_circuit
    device = DEVICES["gpu-sv"]
    jobs = gpu_jobs(args)
    print(f"{len(jobs)} job(s) on {device}, {args.shots} shots each (noise-free statevector, sampled):")
    for j in jobs:
        inst = hi.make(j["family"], j["n"], j["seed"])
        qc, cx = build_hardware_circuit(inst.Q, j["angles"], p=j["p"])
        print(f"  {j['family']:13s} n={j['n']} seed={j['seed']} p={j['p']} angles from n={j['angles_from_n']} "
              f"({qc.num_qubits} qubits, {cx} CX)")
        j.update(inst=inst, qc=qc, cx=cx)
    if not args.submit:
        print("\nDry run. Add --submit to send these jobs to qBraid.")
        return
    from src.hardware import log_run, submit_qbraid
    path = RESULTS_DIR / "hardness_gpu.csv"
    for j in jobs:
        milp = hard_milp.solve(j["inst"], time_limit=600)
        job = submit_qbraid(j["qc"], device, shots=args.shots)
        job_id = job.id
        log_run(device, job_id, args.shots, hour="", p=j["p"], cx_gates=j["cx"],
                note=f"milp_hardness {j['family']} n={j['n']} seed={j['seed']}")
        append_row(path, dict(family=j["family"], n=j["n"], seed=j["seed"], p=j["p"],
                              angles_from_n=j["angles_from_n"], angles=angles_str(j["angles"]), job_id=job_id,
                              shots=args.shots, milp_cost=milp["cost"], milp_seconds=round(milp["seconds"], 3),
                              milp_timeout=milp["timeout"]))
        print(f"submitted {job_id}", flush=True)


def cmd_gpu_fetch(args):
    from qbraid.runtime import load_job
    path = RESULTS_DIR / "hardness_gpu.csv"
    out = RESULTS_DIR / "hardness_gpu_results.csv"
    have = {r["job_id"] for r in read_rows(out)}
    for r in read_rows(path):
        if r["job_id"] in have:
            continue
        job = load_job(r["job_id"])
        status = str(job.status())
        if "COMPLETED" not in status:
            print(f"{r['job_id']}: {status}")
            continue
        counts = job.result().data.get_counts()
        inst = hi.make(r["family"], int(r["n"]), int(r["seed"]))
        n = inst.n
        best, hits, feas, total = np.inf, 0, 0, 0
        e_opt = float(r["milp_cost"]) if r["milp_cost"] not in ("", "None") else None
        for key, c in counts.items():
            k = int(key.replace(" ", ""), 2) if isinstance(key, str) else int(key)
            x = (k >> np.arange(n)) & 1
            e = inst.energy(x)
            best = min(best, e)
            total += c
            feas += c * inst.feasible(x)
            if e_opt is not None and abs(e - e_opt) < 1e-6:
                hits += c
        append_row(out, dict(r, p_opt_est=hits / total, p_feasible_est=feas / total, best_energy=best,
                             found_opt=hits > 0))
        (RESULTS_DIR / f"hardness_gpu_{r['job_id'].replace(':', '_')}.json").write_text(json.dumps(counts))
        print(f"{r['family']} n={r['n']} seed={r['seed']}: {hits}/{total} optimal, {feas}/{total} feasible, "
              f"best {best} vs MILP {e_opt}")


# ---------------------------------------------------------------- summary
def _gmean(v):
    v = np.asarray([x for x in v if np.isfinite(x)], dtype=float)
    return np.exp(np.mean(np.log(v))) if len(v) else np.inf


def _fit_slope(ns, ys):
    """log2(y) ~ a + b n  ->  b (doublings per added plant). Only finite, positive y."""
    pts = [(n, np.log2(y)) for n, y in zip(ns, ys) if np.isfinite(y) and y > 0]
    if len(pts) < 3:
        return np.nan
    x, y = np.array(pts).T
    return np.polyfit(x, y, 1)[0]


def cmd_summary(args):
    rows = read_rows(RESULTS_DIR / "hardness_milp.csv")
    if rows:
        print("### MILP (HiGHS) effort vs size\n")
        print("| Family | n | MILP vars | Median time | Median nodes | Max nodes | Timeouts |")
        print("|---|---|---|---|---|---|---|")
        for fam in hi.FAMILIES:
            for n in sorted({int(r["n"]) for r in rows if r["family"] == fam}):
                g = [r for r in rows if r["family"] == fam and int(r["n"]) == n]
                t = [float(r["seconds"]) for r in g]
                nodes = [int(r["nodes"]) for r in g]
                to = sum(r["timeout"] == "True" for r in g)
                print(f"| {fam} | {n} | {g[0]['milp_vars']} | {np.median(t):.2f} s | {np.median(nodes):,.0f} | "
                      f"{max(nodes):,} | {to} / {len(g)} |")
        print()
    for fam in hi.FAMILIES:
        q = read_rows(RESULTS_DIR / f"hardness_quantum_{fam}.csv")
        if not q:
            continue
        methods = [m for m in ("random", "qaoa_p1", "qaoa_p2", "qaoa_p3", "qaoa_p1_transfer", "sa")
                   if any(r["method"] == m for r in q)]
        sizes = sorted({int(r["n"]) for r in q})
        print(f"### {fam}: exact success probability per shot (geometric mean over seeds)\n")
        print("| n | MILP time / nodes | " + " | ".join(methods) + " |")
        print("|---|---|" + "---|" * len(methods))
        slopes = {m: ([], []) for m in methods}
        for n in sizes:
            g = [r for r in q if int(r["n"]) == n]
            mt = np.median([float(r["milp_seconds"]) for r in g if r["method"] == "random"])
            mn = np.median([int(r["milp_nodes"]) for r in g if r["method"] == "random"])
            cells = []
            for m in methods:
                ps = [float(r["p_success"]) for r in g if r["method"] == m]
                if not ps:
                    cells.append("—")
                    continue
                if m == "sa":
                    k = sum(p > 0 for p in ps)
                    cells.append(f"{np.mean(ps):.3f} ({k}/{len(ps)} inst.)")
                else:
                    gm = _gmean(ps)
                    cells.append(f"{gm:.2e}")
                    slopes[m][0].append(n)
                    slopes[m][1].append(gm)
            print(f"| {n} | {mt:.3f} s / {mn:,.0f} | " + " | ".join(cells) + " |")
        print("\nHalvings of p_opt per added plant (fit of log2 p_opt vs n; random = 1 when there is one optimum):")
        for m in methods:
            if m != "sa" and slopes[m][0]:
                print(f"  {m:18s} {-_fit_slope(*slopes[m]):.3f}")
        # Feasibility and tuning time at the largest size.
        n = sizes[-1]
        print(f"\nAt n={n}: mean p_feasible / normalized mean energy / tuning s:")
        for m in methods:
            g = [r for r in q if int(r["n"]) == n and r["method"] == m]
            if g:
                print(f"  {m:18s} {np.mean([float(r['p_feasible']) for r in g]):.3f} / "
                      f"{np.mean([float(r['mean_norm']) for r in g]):.4f} / "
                      f"{np.mean([float(r['seconds']) for r in g]):.1f}")
        print()
    gpu = read_rows(RESULTS_DIR / "hardness_gpu_results.csv")
    if gpu:
        print("### gpu-sv (noise-free statevector, sampled)\n")
        print("| Family | n | Seed | Job ID | Shots | Optimal shots | Feasible shots | Best energy | MILP optimum |")
        print("|---|---|---|---|---|---|---|---|---|")
        for r in gpu:
            print(f"| {r['family']} | {r['n']} | {r['seed']} | {r['job_id']} | {r['shots']} | "
                  f"{float(r['p_opt_est']):.2e} | {float(r['p_feasible_est']):.3f} | {r['best_energy']} | {r['milp_cost']} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["milp", "quantum", "gpu", "gpu-fetch", "summary"])
    ap.add_argument("--family", nargs="+", default=list(hi.FAMILIES), choices=hi.FAMILIES)
    ap.add_argument("--sizes", nargs="+", type=int)
    ap.add_argument("--p", nargs="+", type=int, default=[1, 2, 3])
    ap.add_argument("--time-limit", type=float, default=30.0)
    ap.add_argument("--gpu-sizes", nargs="+", type=int, default=list(GPU_SIZES))
    ap.add_argument("--gpu-seeds", type=int, default=1)
    ap.add_argument("--gpu-p", type=int, default=1)
    ap.add_argument("--shots", type=int, default=GPU_SHOTS)
    ap.add_argument("--submit", action="store_true")
    args = ap.parse_args()
    if args.sizes is None:
        args.sizes = list(MILP_SIZES if args.cmd == "milp" else QUANTUM_SIZES)
    {"milp": cmd_milp, "quantum": cmd_quantum, "gpu": cmd_gpu, "gpu-fetch": cmd_gpu_fetch,
     "summary": cmd_summary}[args.cmd](args)


if __name__ == "__main__":
    main()

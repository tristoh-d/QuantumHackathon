"""Different simulated backends for hour-by-hour QAOA, on real TVA load shapes (5-plant fleet), vs the MILP.

    python -m experiments.tva_sims run --config ideal-p1        # one config (run several in parallel)
    python -m experiments.tva_sims run --config all             # every config, one after the other
    python -m experiments.tva_sims summary                      # merge results/tva_sims_*.csv, print tables

Days: the same 40 TVA days as `tva_benchmark quantum` (5 per season x day type, day seed 11), scaled so
the TVA fleet's 17,735 MW maps to the 5-plant fleet's 850 MW. Every day is also solved by the MILP.

Configs (angles are always tuned on the noise-free statevector, as you would before a hardware run;
only the distribution the shots are drawn from changes):
  ideal-p1 / ideal-p2   exact statevector probabilities (what benchmark.py uses)
  forte-p1 / forte-p2   depolarizing noise near IonQ Forte-1's published figures: 0.02% per 1-qubit gate,
                        0.4% per 2-qubit gate, 0.5% readout
  noisy-p1              0.1% 1-qubit, 2% 2-qubit, 2% readout
  vnoisy-p1             0.2% 1-qubit, 5% 2-qubit, 3% readout
  random                uniform guessing
Noisy probabilities come from an Aer density-matrix simulation of the circuit transpiled to
rz/sx/x/cx (the 5-plant p=1 circuit has 56 CX), with readout error applied to each qubit. Drawing
`shots` samples from them is the same as running the noisy circuit with that many shots.
"""
import argparse
import csv
import time
from dataclasses import replace

import numpy as np

from experiments._common import todo_guard
from src import demand as tva
from src import quantum
from src.classical import run_milp
from src.config import RESULTS_DIR, load_problem
from src.scheduler import run_day

NOISE = {  # name -> (1-qubit gate error, 2-qubit gate error, readout error)
    "forte": (2e-4, 4e-3, 5e-3),
    "noisy": (1e-3, 2e-2, 2e-2),
    "vnoisy": (2e-3, 5e-2, 3e-2),
}
CONFIGS = {  # name -> (sampler, p, noise)
    "ideal-p1": ("qaoa", 1, None),
    "ideal-p2": ("qaoa", 2, None),
    "forte-p1": ("qaoa", 1, "forte"),
    "forte-p2": ("qaoa", 2, "forte"),
    "noisy-p1": ("qaoa", 1, "noisy"),
    "vnoisy-p1": ("qaoa", 1, "vnoisy"),
    "random": ("random", 1, None),
}
FIELDS = ["config", "shots", "season", "daytype", "date", "milp_cost", "cost", "gap_pct", "valid", "violations",
          "hours_matching_best", "mean_valid_share", "mean_p_best", "seconds"]
DAY_SEED, PER_STRATUM, SAMPLER_SEED = 11, 5, 7


# ---------------------------------------------------------------- noisy QAOA
_ideal_run_qaoa = quantum.run_qaoa
_sim_cache = {}


def _simulator(noise):
    if noise not in _sim_cache:
        from qiskit_aer import AerSimulator
        from qiskit_aer.noise import NoiseModel, depolarizing_error
        e1, e2, _ = NOISE[noise]
        nm = NoiseModel()
        nm.add_all_qubit_quantum_error(depolarizing_error(e1, 1), ["sx", "x"])   # rz is virtual on hardware
        nm.add_all_qubit_quantum_error(depolarizing_error(e2, 2), ["cx"])
        _sim_cache[noise] = AerSimulator(method="density_matrix", noise_model=nm)
    return _sim_cache[noise]


def apply_readout(probs, n_qubits, ro):
    """Flip each measured bit with probability ro (bit j of the index = qubit j)."""
    t = probs.reshape((2,) * n_qubits)        # axis 0 = highest qubit
    m = np.array([[1 - ro, ro], [ro, 1 - ro]])
    for axis in range(n_qubits):
        t = np.moveaxis(np.tensordot(m, t, axes=([1], [axis])), 0, axis)
    return t.reshape(-1)


def noisy_probs(Q, angles, p, noise):
    from qiskit import transpile
    import qiskit_aer  # noqa: F401  (adds QuantumCircuit.save_probabilities)
    qc, params = quantum.qaoa_circuit(Q, p)
    bound = qc.assign_parameters(dict(zip(params, angles)))
    t = transpile(bound, basis_gates=["rz", "sx", "x", "cx"], optimization_level=1)
    assert [t.find_bit(q).index for q in t.qubits] == list(range(len(Q)))
    t.save_probabilities()
    probs = np.asarray(_simulator(noise).run(t).result().data()["probabilities"])
    return apply_readout(probs, len(Q), NOISE[noise][2])


def patch_qaoa(noise):
    """Make the scheduler's QAOA draw its shots from the noisy circuit (None: noise-free)."""
    if noise is None:
        quantum.run_qaoa = _ideal_run_qaoa
        return

    def run_qaoa_noisy(Q, offset, p=1, start=None, maxiter=60):
        angles, _ = _ideal_run_qaoa(Q, offset, p=p, start=start, maxiter=maxiter)
        return angles, noisy_probs(Q, angles, p, noise)
    quantum.run_qaoa = run_qaoa_noisy


# ---------------------------------------------------------------- runs
def tva_days(cap):
    days = []
    for k, (season, daytype) in enumerate((s, t) for s in tva.SEASON_ORDER for t in tva.DAYTYPES):
        days += tva.sample_days(season, daytype, n=PER_STRATUM, seed=DAY_SEED + k, replace=False, scale_to=cap)
    return days


def run_config(name, shots_list):
    sampler, p, noise = CONFIGS[name]
    patch_qaoa(noise)
    base = load_problem("5")
    days = tva_days(sum(pl["pmax_mw"] for pl in base.plants))
    rows = []
    start = time.perf_counter()
    for day in days:
        prob = replace(base, demand=day.demand.astype(float), reserve=day.reserve.astype(float), day=day.date)
        milp_cost = run_milp(prob)["cost"]
        for shots in shots_list:
            with todo_guard(name):
                r = run_day(prob, milp_cost, sampler=sampler, p=p, shots=shots, seed=SAMPLER_SEED)
            log = r["log"]
            rows.append(dict(config=name, shots=shots, season=day.season, daytype=day.daytype, date=day.date,
                             milp_cost=round(milp_cost), cost=round(r["total_cost"]), gap_pct=round(r["gap_pct"], 3),
                             valid=int(not r["violations"]), violations=len(r["violations"]),
                             hours_matching_best=sum(h["matches_best"] for h in log),
                             mean_valid_share=round(float(np.mean([h["valid_share"] for h in log])), 4),
                             mean_p_best=round(float(np.mean([h["p_best"] for h in log])), 4),
                             seconds=round(r["seconds"], 2)))
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"tva_sims_{name}.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{name}: {len(days)} days x {shots_list} shots in {time.perf_counter() - start:.0f} s -> {path.name}")


def boot_ci(x, reps=2000):
    x = np.asarray(x, dtype=float)
    return np.percentile([np.random.default_rng(i).choice(x, len(x)).mean() for i in range(reps)], [2.5, 97.5])


def summary():
    rows = []
    for name in CONFIGS:
        path = RESULTS_DIR / f"tva_sims_{name}.csv"
        if path.exists():
            with open(path, newline="") as f:
                rows += list(csv.DictReader(f))
    if not rows:
        print("no results/tva_sims_*.csv yet")
        return
    shots_list = sorted({int(r["shots"]) for r in rows})
    print("| Config | Shots | Valid days | Gap vs MILP, all days (mean [95% CI]) | Gap, valid days | Valid-shot share "
          "| Best-choice share | Hours matching best | Time per day |")
    print("|---|---|---|---|---|---|---|---|---|")
    for shots in shots_list:
        for name in CONFIGS:
            r = [x for x in rows if x["config"] == name and int(x["shots"]) == shots]
            if not r:
                continue
            g = np.array([float(x["gap_pct"]) for x in r])
            lo, hi = boot_ci(g)
            gv = [float(x["gap_pct"]) for x in r if x["valid"] == "1"]
            avg = lambda k: np.mean([float(x[k]) for x in r])  # noqa: E731
            print(f"| {name} | {shots} | {sum(x['valid'] == '1' for x in r)} / {len(r)} | {g.mean():+.2f}% "
                  f"[{lo:+.2f}, {hi:+.2f}] | {np.mean(gv):+.2f}% | {avg('mean_valid_share'):.2f} | "
                  f"{avg('mean_p_best'):.3f} | {avg('hours_matching_best'):.1f} | {avg('seconds'):.1f} s |"
                  if gv else f"| {name} | {shots} | 0 / {len(r)} | {g.mean():+.2f}% | — | | | | |")
    print()
    for shots in shots_list:
        base = {x["date"]: x for x in rows if x["config"] == "ideal-p1" and int(x["shots"]) == shots}
        for name in CONFIGS:
            if name == "ideal-p1":
                continue
            other = {x["date"]: x for x in rows if x["config"] == name and int(x["shots"]) == shots}
            both = [d for d in base if d in other and base[d]["valid"] == "1" and other[d]["valid"] == "1"]
            if not both:
                continue
            diff = np.array([float(other[d]["gap_pct"]) - float(base[d]["gap_pct"]) for d in both])
            print(f"{shots} shots, {name} vs ideal-p1 on {len(both)} days valid for both: "
                  f"{name} cheaper {np.sum(diff < -1e-9)}, tie {np.sum(np.abs(diff) <= 1e-9)}, "
                  f"dearer {np.sum(diff > 1e-9)}, mean {diff.mean():+.2f} points")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["run", "summary"])
    ap.add_argument("--config", default="all", choices=["all"] + list(CONFIGS))
    ap.add_argument("--shots", type=int, nargs="+", default=[20, 50])
    args = ap.parse_args()
    if args.action == "summary":
        summary()
        return
    for name in (CONFIGS if args.config == "all" else [args.config]):
        run_config(name, args.shots)


if __name__ == "__main__":
    main()

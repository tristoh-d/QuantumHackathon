"""Two-hour startup decisions with one QAOA layer and classical dispatch."""
from functools import lru_cache
from itertools import product
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
from qiskit import QuantumCircuit
from qiskit.circuit.library import DiagonalGate
from qiskit.quantum_info import Statevector

from check import (check_schedule, hour_cost, hour_ok, load_demand, load_plants,
                   locks, solve_milp)


def circuit(energy, gamma, beta):
    n = (len(energy) - 1).bit_length()
    qc = QuantumCircuit(n)
    qc.h(range(n))
    qc.append(DiagonalGate(np.exp(-1j * gamma * energy)), range(n))
    qc.rx(2 * beta, range(n))
    return qc


def run(output=None):
    start = perf_counter()
    plants = load_plants()
    demand, reserve = load_demand()
    initial = tuple(int(p["on_at_start"]) for p in plants)
    masks = list(product((0, 1), repeat=len(plants)))

    @lru_cache(None)
    def choices(t, previous, must_on, must_off):
        options = [(hour_cost(plants, demand[t], mask, previous), mask)
                   for mask in masks
                   if hour_ok(plants, demand[t], reserve[t], mask, must_on, must_off)]
        return sorted(options)

    def options(t, history):
        on, off = locks(plants, history)
        return choices(t, history[-1] if history else initial, tuple(on), tuple(off))

    def complete(history, stop):
        history = list(history)
        for t in range(len(history), stop):
            candidates = options(t, history)
            if not candidates:
                return None
            history.append(candidates[0][1])
        return history

    # Same observed history for every candidate. Coal stays online in hours 5 and 6.
    prefix = complete([], 5)
    if prefix is None or initial != (1, 0, 0, 0, 0) or len(plants) != 5:
        raise ValueError("This case study expects the track's five-plant fleet.")
    paths, costs = {}, np.full(256, np.inf)
    for index in range(256):
        history = list(prefix)
        for step in range(2):
            mask = (1,) + tuple((index >> (4 * step + j)) & 1 for j in range(4))
            if mask not in {m for _, m in options(5 + step, history)}:
                break
            history.append(mask)
        else:
            day = complete(history, len(demand))
            if day is not None:
                report = check_schedule(plants, demand, reserve, day, verbose=False)
                if report["valid"]:
                    paths[index] = day
                    costs[index] = report["total_cost"]
    valid = np.isfinite(costs)
    if not valid.any():
        raise ValueError("No feasible completed schedule in this decision window.")
    minimum = costs.min()
    maximum = costs[valid].max()
    energy = np.full(256, 2.0)
    energy[valid] = (costs[valid] - minimum) / max(1.0, maximum - minimum)
    optimal = valid & np.isclose(costs, minimum, atol=0.005, rtol=0)
    setup = perf_counter() - start

    # Batched exact statevector grid search. XOR flips one little-endian qubit.
    tick = perf_counter()
    gammas = np.linspace(0, 2*np.pi, 33)
    initial_states = np.exp(-1j * gammas[:, None] * energy) / 16
    indices = np.arange(256)
    best_mean = np.inf
    for beta in np.linspace(-np.pi/2, np.pi/2, 33):
        states = initial_states.copy()
        for j in range(8):
            states = np.cos(beta)*states - 1j*np.sin(beta)*states[:, indices ^ (1 << j)]
        probabilities = np.abs(states)**2
        means = probabilities @ energy
        i = int(means.argmin())
        if means[i] < best_mean:
            best_mean = means[i]
            angles = float(gammas[i]), float(beta)
            reference = probabilities[i]
    qc = circuit(energy, *angles)
    prob = Statevector.from_instruction(qc).probabilities()
    np.testing.assert_allclose(prob, reference, atol=1e-10)
    tune = perf_counter() - tick

    exact_cost, exact_day, _, solve_seconds = solve_milp(plants, demand, reserve)
    greedy_day = complete([], len(demand))
    rank = sorted(range(5), key=lambda i: plants[i]["marginal_cost_per_mwh"] +
                  plants[i]["no_load_cost_per_h"]/plants[i]["pmax_mw"])
    ranked_day = []
    for need in demand + reserve:
        mask = [0]*5
        capacity = 0
        for i in rank:
            mask[i] = 1
            capacity += plants[i]["pmax_mw"]
            if capacity >= need:
                break
        ranked_day.append(mask)

    results = []
    for shots in (5, 10, 20, 50, 200):
        for method, distribution in (("QAOA", prob), ("Uniform", np.full(256, 1/256))):
            for seed in range(100):
                draws = np.random.default_rng(seed).choice(256, shots, p=distribution)
                results.append((method, shots, seed, valid[draws].mean(),
                                int(optimal[draws].any()), costs[draws].min()))
    trials = pd.DataFrame(results, columns=["method", "shots", "seed", "feasible_share",
                                           "hit_window_best", "best_cost"])
    # A declared seed and budget chosen before reading the samples.
    demo = np.random.default_rng(0).choice(256, 20, p=prob)
    best_sample = demo[np.argmin(costs[demo])]
    plans = {"Full-day MILP": exact_day, "Starter cheapest-first": ranked_day,
             "One-hour least cost": greedy_day, "Exact window search": paths[int(costs.argmin())]}
    if valid[best_sample]:
        plans["QAOA 20 shots seed 0"] = paths[best_sample]
    summary, hourly = [], []
    for name, day in plans.items():
        if day is None:
            continue
        r = check_schedule(plants, demand, reserve, day, exact_cost, verbose=False)
        summary.append((name, r["total_cost"], len(r["violations"]), r["startup_cost"], r["gap_pct"]))
        for t, mask in enumerate(day):
            hourly.append((name, t, *mask, demand[t], reserve[t]))
    if not check_schedule(plants, demand, reserve, exact_day, verbose=False)["valid"]:
        raise AssertionError("MILP baseline failed independent schedule verification.")
    np.testing.assert_allclose(summary[0][1], exact_cost, atol=.01, rtol=0)
    summary = pd.DataFrame(summary, columns=["method","day_cost","violations","startup_cost","gap_pct"])
    hourly = pd.DataFrame(hourly, columns=["method","hour",*[p["plant_id"] for p in plants],"demand","reserve"])
    metrics = pd.DataFrame([{"valid_windows":sum(valid),"optimal_windows":sum(optimal),
                            "qaoa_best_probability":prob[optimal].sum(),"uniform_best_probability":optimal.mean(),
                            "gamma":angles[0],"beta":angles[1],"classical_table_seconds":setup,
                            "tune_and_statevector_seconds":tune,"milp_solver_seconds":solve_seconds}])
    if output is not None:
        directory = Path(output)
        directory.mkdir(exist_ok=True, parents=True)
        for name, frame in (("summary",summary),("hourly",hourly),("trials",trials),("metrics",metrics)):
            frame.to_csv(directory / (name+".csv"), index=False)
    return summary, hourly, trials, metrics, qc


if __name__ == "__main__":
    summary, _, trials, metrics, _ = run(Path(__file__).parent / "results")
    print(summary.to_string(index=False))
    print(metrics.to_string(index=False))
    print(trials.groupby(["shots","method"]).hit_window_best.mean())

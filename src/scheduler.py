"""The whole day, hour by hour (Milestone 4). Provided by the organizers, refactored to take a Problem.

For each hour, schedule_day:
1. asks check.locks which plants min up / min down times force on or off (classical);
2. builds your QUBO, plus a penalty for breaking those locks;
3. runs QAOA, starting from the previous hour's angles (warm start);
4. draws `shots` samples, like a quantum computer would;
5. keeps the cheapest sampled on/off choice that passes the classical check
   (hour_ok, exact hour_cost);
6. carries that choice forward as "who was on" for the next hour.

If no sample passes, it keeps a choice that breaks a lock (or, failing that, the most
common sample), and the checker lists the broken rule.

sampler="random" swaps QAOA for uniform random guessing: the honesty check.
"""
import time

import numpy as np

from src.check import check_hour, check_schedule, hour_cost, hour_ok, locks
from src.config import N_SLACK, Problem
from src.qubo import add_locks, build_qubo, choice_to_index, index_bits, plant_hour_costs, plant_index


def schedule_day(problem: Problem, p=1, shots=200, sampler="qaoa", seed=7, penalty=None,
                 n_slack=N_SLACK, maxiter=60):
    """Run the hour-by-hour loop. Returns (schedule [hours x plants], log [one dict per hour])."""
    plants, demand, reserve, n = problem.plants, problem.demand, problem.reserve, problem.n
    n_qubits = n + n_slack
    bits, pidx = index_bits(n_qubits), plant_index(n, n_qubits)
    if sampler == "qaoa":
        from src.quantum import choice_probs, run_qaoa     # qiskit only needed for QAOA
    elif sampler == "random":
        def choice_probs(probs, n_plants):
            return np.bincount(pidx, weights=probs, minlength=2 ** n_plants)
    else:
        raise ValueError(f"unknown sampler {sampler!r}: use 'qaoa' or 'random'")

    rng = np.random.default_rng(seed)
    history, log, angles = [], [], None
    was_on = problem.start_state
    for t in problem.hours:
        must_on, must_off = locks(plants, history)
        Q, offset = build_qubo(plants, demand[t], reserve[t], was_on, penalty=penalty, n_slack=n_slack)
        Q, offset = add_locks(Q, offset, must_on, must_off, weight=2 * plant_hour_costs(plants, was_on).max())
        if sampler == "qaoa":
            angles, probs = run_qaoa(Q, offset, p=p, start=angles, maxiter=maxiter)
        else:
            probs = np.full(2 ** n_qubits, 1 / 2 ** n_qubits)
        samples = rng.choice(2 ** n_qubits, size=shots, p=probs / probs.sum())
        seen = [list(bits[k][:n]) for k in np.unique(pidx[samples])]
        ok = [c for c in seen if hour_ok(plants, demand[t], reserve[t], c, must_on, must_off)]
        if not ok:                              # nothing fully valid: allow breaking a lock
            ok = [c for c in seen if hour_ok(plants, demand[t], reserve[t], c)]
        if ok:
            pick = min(ok, key=lambda c: hour_cost(plants, demand[t], c, was_on))
        else:                                   # still nothing: take the most common sample
            pick = list(bits[np.bincount(pidx[samples]).argmax()][:n])
        ref = check_hour(plants, demand[t], reserve[t], pick, was_on, must_on, must_off, verbose=False)
        best_k = None if ref["best_choice"] is None else choice_to_index(ref["best_choice"])
        valid_share = np.mean([hour_ok(plants, demand[t], reserve[t], bits[k][:n], must_on, must_off)
                               for k in samples])
        log.append(dict(hour=int(t), pick=pick, matches_best=ref["matches_best"], valid_share=valid_share,
                        p_best=0.0 if best_k is None else choice_probs(probs, n)[best_k],
                        must_on=must_on, must_off=must_off, was_on=list(was_on),
                        Q=Q, offset=offset, angles=angles))
        history.append(pick)
        was_on = pick
    return np.array(history), log


def run_day(problem: Problem, milp_cost=None, verbose=False, **kwargs) -> dict:
    """schedule_day + check_schedule + wall-clock seconds, in one dict."""
    start = time.perf_counter()
    schedule, log = schedule_day(problem, **kwargs)
    seconds = time.perf_counter() - start
    result = check_schedule(problem.plants, problem.demand, problem.reserve, schedule,
                            milp_cost=milp_cost, verbose=verbose)
    result.update(schedule=schedule, log=log, seconds=seconds)
    return result

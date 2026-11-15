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
sampler="all" proposes every on/off choice (no sampling): the ceiling for a given step 5.

lookahead=H (hybrid, src/lookahead.py) changes step 5: each valid sampled choice is scored by
this hour plus the optimal next H hours (a small MILP with the past fixed), instead of this
hour alone. H=0 is the plain hour-by-hour rule. max_candidates=K keeps only the K choices
QAOA sampled most often before the look-ahead scores them. shape_qubo=True (needs lookahead) also
replaces each plant's one-hour cost c_i in the QUBO by its look-ahead value (best cost with the
plant on minus off, over the next H hours), so QAOA proposes choices that pay off later.

reduce=True (default) removes the qubits whose value is known before sampling (quantum.fixed_bits:
locked plants, slack bits the hour cannot use). QAOA runs on fewer qubits, and the random sampler
guesses only the remaining bits, so the QAOA vs random comparison stays like for like.
reduce=False is the original full-size QUBO for both samplers.
"""
import time

import numpy as np

from src.check import check_hour, check_schedule, hour_cost, hour_ok, locks
from src.config import N_SLACK, Problem
from src.lookahead import Lookahead
from src.qubo import add_locks, build_qubo, choice_to_index, index_bits, plant_hour_costs, plant_index


def schedule_day(problem: Problem, p=1, shots=200, sampler="qaoa", seed=7, penalty=None,
                 n_slack=N_SLACK, maxiter=60, lookahead=0, max_candidates=None, shape_qubo=False, reduce=True):
    """Run the hour-by-hour loop. Returns (schedule [hours x plants], log [one dict per hour])."""
    plants, demand, reserve, n = problem.plants, problem.demand, problem.reserve, problem.n
    n_qubits = n + n_slack
    bits, pidx = index_bits(n_qubits), plant_index(n, n_qubits)
    if sampler == "qaoa":
        from src.quantum import choice_probs, run_qaoa     # qiskit only needed for QAOA
    elif sampler in ("random", "all"):
        def choice_probs(probs, n_plants):
            return np.bincount(pidx, weights=probs, minlength=2 ** n_plants)
    else:
        raise ValueError(f"unknown sampler {sampler!r}: use 'qaoa', 'random' or 'all'")
    from src.quantum import embed_probs, fixed_bits
    ahead = Lookahead(plants, demand, reserve, lookahead) if lookahead else None

    rng = np.random.default_rng(seed)
    history, log, angles = [], [], None
    was_on = problem.start_state
    for t in problem.hours:
        must_on, must_off = locks(plants, history)
        c = plant_hour_costs(plants, was_on)
        if shape_qubo and ahead is not None:            # hybrid: QUBO costs from the look-ahead
            Q, offset, q_on, q_off, lock_weight = shaped_qubo(ahead, history, c, plants, demand[t], reserve[t],
                                                              was_on, penalty, n_slack, must_on, must_off)
        else:
            Q, offset = build_qubo(plants, demand[t], reserve[t], was_on, penalty=penalty, n_slack=n_slack)
            q_on, q_off, lock_weight = must_on, must_off, 2 * c.max()
        Q, offset = add_locks(Q, offset, q_on, q_off, weight=lock_weight)
        fixed = fixed_bits(plants, demand[t], reserve[t], q_on, q_off, n_slack) if reduce else {}
        if sampler == "qaoa" and fixed:
            angles, probs = run_qaoa(Q, offset, p=p, start=angles, maxiter=maxiter, fixed=fixed)
        elif sampler == "qaoa":
            angles, probs = run_qaoa(Q, offset, p=p, start=angles, maxiter=maxiter)
        else:
            free = [j for j in range(n_qubits) if j not in fixed]
            probs = embed_probs(np.full(2 ** len(free), 2.0 ** -len(free)), free, fixed, n_qubits)
        samples = rng.choice(2 ** n_qubits, size=shots, p=probs / probs.sum())
        kinds, counts = np.unique(pidx[samples], return_counts=True)
        if sampler == "all":
            kinds, counts = np.arange(2 ** n), np.ones(2 ** n, dtype=int)
        seen = [list(bits[k][:n]) for k in kinds]
        ok = [c for c in seen if hour_ok(plants, demand[t], reserve[t], c, must_on, must_off)]
        locks_kept = bool(ok)
        if not ok:                              # nothing fully valid: allow breaking a lock
            ok = [c for c in seen if hour_ok(plants, demand[t], reserve[t], c)]
        if max_candidates:                      # keep the K choices sampled most often
            count = dict(zip(kinds.tolist(), counts.tolist()))
            ok = sorted(ok, key=lambda ch: -count[choice_to_index(ch)])[:max_candidates]
        pick = None
        if ok and ahead is not None and locks_kept:     # hybrid: score by this hour + next H hours
            pick, _ = ahead.best(history, ok)           # None if every candidate is a dead end
        if pick is None and ok:
            pick = min(ok, key=lambda c: hour_cost(plants, demand[t], c, was_on))
        elif pick is None:                      # still nothing: take the most common sample
            pick = list(bits[np.bincount(pidx[samples]).argmax()][:n])
        ref = check_hour(plants, demand[t], reserve[t], pick, was_on, must_on, must_off, verbose=False)
        best_k = None if ref["best_choice"] is None else choice_to_index(ref["best_choice"])
        valid_share = np.mean([hour_ok(plants, demand[t], reserve[t], bits[k][:n], must_on, must_off)
                               for k in samples])
        log.append(dict(hour=int(t), pick=pick, matches_best=ref["matches_best"], valid_share=valid_share,
                        p_best=0.0 if best_k is None else choice_probs(probs, n)[best_k],
                        must_on=must_on, must_off=must_off, was_on=list(was_on), n_candidates=len(ok),
                        lookahead_solves=ahead.solves if ahead else 0,
                        Q=Q, offset=offset, angles=angles, fixed=fixed))
        history.append(pick)
        was_on = pick
    return np.array(history), log


def shaped_qubo(ahead, history, c, plants, demand_mw, reserve_mw, was_on, penalty, n_slack,
                must_on=(), must_off=()):
    """build_qubo with c_i swapped for the look-ahead value of plant i. Returns (Q, offset, must_on,
    must_off, lock weight).

    A value of +inf (on now leads to a dead end) or -inf (off now does) becomes an extra lock, like the
    min up / min down locks, instead of a huge cost; so do plants already locked. The penalty A and
    lock weight are 2x the largest remaining |value| (at least 2x the largest c_i of a free plant,
    so the QUBO never collapses to zero).
    """
    v = ahead.plant_values(history)
    must_on = sorted(set(must_on) | {i for i in range(len(plants)) if v[i] == -np.inf})
    must_off = sorted(set(must_off) | {i for i in range(len(plants)) if v[i] == np.inf} - set(must_on))
    free = [i for i in range(len(plants)) if i not in must_on and i not in must_off]
    v = np.where(np.isfinite(v), v, 0.0)
    scale = max([abs(v[i]) for i in free] + [1.0])
    A = 2 * scale if penalty is None else penalty
    Q, offset = build_qubo(plants, demand_mw, reserve_mw, was_on, penalty=A, n_slack=n_slack)
    for i in range(len(plants)):
        Q[i, i] += v[i] - c[i]
    return Q, offset, must_on, must_off, A


def run_day(problem: Problem, milp_cost=None, verbose=False, **kwargs) -> dict:
    """schedule_day + check_schedule + wall-clock seconds, in one dict."""
    start = time.perf_counter()
    schedule, log = schedule_day(problem, **kwargs)
    seconds = time.perf_counter() - start
    result = check_schedule(problem.plants, problem.demand, problem.reserve, schedule,
                            milp_cost=milp_cost, verbose=verbose)
    result.update(schedule=schedule, log=log, seconds=seconds)
    return result

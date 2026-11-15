"""QAOA for one hour's QUBO (Milestone 4). Provided by the organizers, optimized by the team; needs qiskit.

1. qubo_to_ising replaces each bit y with (1 - z)/2, which gives single-qubit Z terms
   and ZZ pair terms.
2. qaoa_circuit builds p layers: the cost layer exp(-i gamma H_cost), then an rx on each qubit
   (the mixer). The cost layer is diagonal, so it is a phase polynomial: one phase per Z term
   and per ZZ term. synthesis="phase_poly" (default) builds it with Gray-code CNOT synthesis
   (Amy, Azimzadeh, Mosca 2018), which shares CNOTs between terms: 35 CX instead of 56 on 8 qubits,
   the same unitary. synthesis="pairs" is the original rz + rzz version.
3. run_qaoa tunes the angles with COBYLA on the exact state. It minimizes the average energy,
   rescaled to the range 0 to 1. The state is computed in numpy (cost layer = one elementwise
   phase, mixer = rx on every qubit), which gives the same probabilities as the circuit and is
   far faster than rebuilding a qiskit Statevector each step. backend="qiskit" keeps the old path.
4. fixed={qubit: 0/1} removes qubits whose value is known before QAOA runs (locked plants,
   slack bits the hour cannot use; see fixed_bits). They are substituted into the QUBO, QAOA runs
   on the smaller problem, and the probabilities are put back on the full bitstring space.
5. choice_probs sums the probability over the slack qubits, giving the chance of each
   on/off choice.

qiskit is imported only where a circuit is built, so the random sampler runs without it.

Honesty note for the deck: to tune the angles, run_qaoa scores every bitstring first,
which already finds the best one. Count that classical work in your timing. fixed_bits is
classical preprocessing too: it only uses the locks and the capacity rule, never the costs.
"""
from functools import lru_cache

import numpy as np
from scipy.optimize import minimize

from src.qubo import all_energies, capacity_weights, blocks_needed, plant_index

SYNTHESES = ("phase_poly", "pairs")


def qubo_to_ising(Q):
    """y = (1 - z) / 2 turns the QUBO into  sum_j h_j Z_j + sum_jk J_jk Z_j Z_k + constant."""
    h, J = np.zeros(len(Q)), {}
    for j in range(len(Q)):
        h[j] -= Q[j, j] / 2
        for k in range(j + 1, len(Q)):
            if Q[j, k] != 0:
                J[(j, k)] = Q[j, k] / 4
                h[j] -= Q[j, k] / 4
                h[k] -= Q[j, k] / 4
    return h, J


def ising_scale(h, J):
    """Largest |h| or |J|: the cost layer is divided by it so the angles stay sane."""
    return max(np.abs(h).max(initial=0.0), max((abs(v) for v in J.values()), default=0.0))


# ---------------------------------------------------------------- circuits
@lru_cache(maxsize=None)
def _phase_poly_skeleton(n, terms):
    """CNOT + rz skeleton for the phase polynomial with these parity terms (tuples of qubits).

    Returns a list of ("cx", (control, target)) and ("rz", (qubit, term index)). The synthesis only
    takes numeric angles (and reduces them mod 2 pi), so term k gets the placeholder 6 (k + 1) / (T + 1),
    all distinct and below 2 pi; every placeholder
    must come back exactly once on one rz, and the circuit's final CNOT network must be the identity
    (synth_cnot_phase_aam guarantees it; tests check the unitary).
    """
    from qiskit.synthesis import synth_cnot_phase_aam
    cols = [[int(q in t) for t in terms] for q in range(n)]
    step = 6.0 / (len(terms) + 1)
    synth = synth_cnot_phase_aam(cols, [step * (i + 1) for i in range(len(terms))])
    ops, used = [], []
    for inst in synth.data:
        qs = [synth.find_bit(q).index for q in inst.qubits]
        name = inst.operation.name
        if name == "cx":
            ops.append(("cx", tuple(qs)))
        elif name in ("rz", "p", "u1"):
            k = int(round(float(inst.operation.params[0]) / step)) - 1
            assert abs(float(inst.operation.params[0]) - step * (k + 1)) < 1e-9, "synthesis changed an angle"
            ops.append(("rz", (qs[0], k)))
            used.append(k)
        else:
            raise RuntimeError(f"unexpected gate {name!r} from phase-polynomial synthesis")
    assert sorted(used) == list(range(len(terms))), "synthesis dropped or repeated a term"
    return tuple(ops)


def _cost_terms(h, J):
    """Non-zero Z and ZZ terms as (qubits tuple, weight)."""
    terms = [((j,), hj) for j, hj in enumerate(h) if hj != 0]
    return terms + [((j, k), v) for (j, k), v in J.items() if v != 0]


def cost_layer(qc, h, J, gamma, scale, synthesis="phase_poly"):
    """Append exp(-i gamma H_cost / scale) (up to a global phase) to qc."""
    terms = _cost_terms(h, J)
    if synthesis == "pairs":
        for (q, *rest), w in terms:
            if rest:
                qc.rzz(2 * gamma * w / scale, q, rest[0])
            else:
                qc.rz(2 * gamma * w / scale, q)
        return qc
    if synthesis != "phase_poly":
        raise ValueError(f"unknown synthesis {synthesis!r}: use one of {SYNTHESES}")
    if not terms:
        return qc
    for kind, args in _phase_poly_skeleton(qc.num_qubits, tuple(t for t, _ in terms)):
        if kind == "cx":
            qc.cx(*args)
        else:
            q, k = args
            qc.rz(2 * gamma * terms[k][1] / scale, q)
    return qc


def qaoa_circuit(Q, p=1, synthesis="phase_poly"):
    """Parameterized QAOA circuit with p layers. Returns (circuit, parameters)."""
    from qiskit import QuantumCircuit
    from qiskit.circuit import ParameterVector
    h, J = qubo_to_ising(Q)
    scale = ising_scale(h, J) or 1.0
    gammas, betas = ParameterVector("gamma", p), ParameterVector("beta", p)
    qc = QuantumCircuit(len(Q))
    qc.h(range(len(Q)))
    for layer in range(p):
        cost_layer(qc, h, J, gammas[layer], scale, synthesis)
        qc.rx(2 * betas[layer], range(len(Q)))
    return qc, list(gammas) + list(betas)


# ---------------------------------------------------------------- removing known qubits
def fixed_bits(plants, demand_mw, reserve_mw, must_on=(), must_off=(), n_slack=3):
    """Qubits whose value is known before QAOA runs, as {qubit: 0 or 1}.

    - Locked plants (min up / min down): must_on -> 1, must_off -> 0. Only when some choice that keeps
      the locks passes hour_ok; otherwise the locks stay soft (QUBO penalty), so the scheduler can
      still fall back to breaking a lock, as before.
    - Slack bits the hour cannot use: the largest spare capacity of any allowed choice is
      S = sum of a_i over plants not forced off, minus r (in blocks). ceil(log2(S + 1)) slack bits
      already write every spare from 0 to S, so the higher ones are fixed to 0. Every allowed choice
      still has a slack setting with zero penalty; the QUBO landscape over choices is unchanged.
      Never more slack bits than n_slack.
    """
    n = len(plants)
    fixed = {}
    if (must_on or must_off) and _locks_feasible(plants, demand_mw, reserve_mw, must_on, must_off):
        fixed.update({int(i): 1 for i in must_on})
        fixed.update({int(i): 0 for i in must_off})
    off = {i for i, v in fixed.items() if v == 0}
    a = capacity_weights(plants, n_slack)[:n]
    spare = sum(a[i] for i in range(n) if i not in off) - blocks_needed(demand_mw, reserve_mw)
    needed = 0 if spare <= 0 else int(np.ceil(np.log2(np.ceil(spare) + 1)))
    fixed.update({n + k: 0 for k in range(min(needed, n_slack), n_slack)})
    return fixed


def _locks_feasible(plants, demand_mw, reserve_mw, must_on, must_off, max_free=16):
    """True if some on/off choice that keeps the locks meets demand + reserve with pmin <= demand."""
    free = [i for i in range(len(plants)) if i not in must_on and i not in must_off]
    pmax = np.array([p["pmax_mw"] for p in plants], float)
    pmin = np.array([p["pmin_mw"] for p in plants], float)
    base_cap, base_floor = pmax[list(must_on)].sum(), pmin[list(must_on)].sum()
    if len(free) > max_free:        # too many to list: the necessary conditions only
        return base_cap + pmax[free].sum() >= demand_mw + reserve_mw and base_floor <= demand_mw
    bits = (np.arange(2 ** len(free))[:, None] >> np.arange(len(free))) & 1
    cap, floor = base_cap + bits @ pmax[free], base_floor + bits @ pmin[free]
    return bool(np.any((cap >= demand_mw + reserve_mw) & (floor <= demand_mw)))


def reduce_qubo(Q, offset, fixed):
    """Substitute the fixed qubits into the QUBO. Returns (Q_small, offset_small, keep).

    keep lists the remaining qubits in order; qubit i of the small QUBO is qubit keep[i] of Q.
    energy_small(y_keep) == energy(y) for every y that agrees with `fixed`.
    """
    n = len(Q)
    U = np.triu(Q)
    keep = [j for j in range(n) if j not in fixed]
    on = [j for j, v in fixed.items() if v]
    S = np.triu(U, 1)
    S = S + S.T                                     # symmetric pair weights, zero diagonal
    Qs = np.triu(U[np.ix_(keep, keep)])
    Qs[np.diag_indices(len(keep))] += S[np.ix_(keep, on)].sum(axis=1)
    offset_s = offset + np.diag(U)[on].sum() + np.triu(U[np.ix_(on, on)], 1).sum()
    return Qs, float(offset_s), keep


def embed_probs(probs_small, keep, fixed, n_qubits):
    """Probabilities over the small QUBO's bitstrings -> over all 2^n_qubits (fixed bits as given)."""
    idx = np.arange(len(probs_small))
    full = sum(1 << j for j, v in fixed.items() if v) + sum((((idx >> i) & 1) << q for i, q in enumerate(keep)),
                                                          np.zeros_like(idx))   # array even if keep is empty
    out = np.zeros(2 ** n_qubits)
    out[np.asarray(full, dtype=np.int64)] = probs_small
    return out


# ---------------------------------------------------------------- tuning
def _numpy_probs(E_scaled, angles, n):
    from src.exact_qaoa import probs
    return probs(E_scaled, angles, n)


OPTIMIZERS = {   # scipy method -> options; maxiter is filled in by run_qaoa
    "COBYLA": {"rhobeg": 0.2},                 # the original optimizer
    "L-BFGS-B": {},                            # finite-difference gradients; same optima, far less overhead
    "Powell": {"xtol": 1e-3},
}


def run_qaoa(Q, offset, p=1, start=None, maxiter=60, fixed=None, backend="numpy", optimizer="L-BFGS-B"):
    """Tune the angles on the exact state. Returns (angles, probabilities of all 2^len(Q) bitstrings).

    fixed: {qubit: 0/1} known before QAOA runs (fixed_bits); QAOA then runs on the remaining qubits.
    backend: "numpy" (fast, default) or "qiskit" (Statevector of qaoa_circuit; same probabilities).
    optimizer: a key of OPTIMIZERS. scipy's COBYLA is pure Python since scipy 1.16 and its own overhead,
    not the simulation, dominates the run time; L-BFGS-B reaches the same optima about 3x faster.
    """
    if fixed:
        Qs, offset_s, keep = reduce_qubo(Q, offset, fixed)
        angles, probs = run_qaoa(Qs, offset_s, p=p, start=start, maxiter=maxiter, backend=backend,
                                 optimizer=optimizer)
        return angles, embed_probs(probs, keep, fixed, len(Q))
    n = len(Q)
    if n == 0:
        return np.asarray(start if start is not None and len(start) == 2 * p else [0.0] * 2 * p, float), np.ones(1)
    E = all_energies(Q, offset)
    span = E.max() - E.min()
    h, J = qubo_to_ising(Q)
    scale = ising_scale(h, J)
    if span == 0 or scale == 0:                       # flat landscape: QAOA can only return uniform
        return np.asarray(start if start is not None and len(start) == 2 * p else [0.0] * 2 * p, float), \
            np.full(2 ** n, 2.0 ** -n)
    E_norm = (E - E.min()) / span

    if backend == "numpy":
        E_scaled = E / scale

        def probs_at(angles):
            return _numpy_probs(E_scaled, angles, n)
    elif backend == "qiskit":
        from qiskit.quantum_info import Statevector
        qc, params = qaoa_circuit(Q, p, synthesis="pairs")

        def probs_at(angles):
            return Statevector(qc.assign_parameters(dict(zip(params, angles)))).probabilities()
    else:
        raise ValueError(f"unknown backend {backend!r}: use 'numpy' or 'qiskit'")

    def average_energy(angles):
        return probs_at(angles) @ E_norm

    if start is None or len(start) != 2 * p:     # coarse grid for one (gamma, beta), used in every layer
        grid = [(g, b) for g in np.linspace(0.1, 3.0, 15) for b in np.linspace(0.1, 1.5, 8)]
        g, b = min(grid, key=lambda gb: average_energy([gb[0]] * p + [gb[1]] * p))
        start = [g] * p + [b] * p
    if optimizer not in OPTIMIZERS:
        raise ValueError(f"unknown optimizer {optimizer!r}: use one of {sorted(OPTIMIZERS)}")
    options = dict(OPTIMIZERS[optimizer], maxiter=maxiter if optimizer != "Powell" else max(1, maxiter // 20))
    result = minimize(average_energy, start, method=optimizer, options=options)
    return result.x, probs_at(result.x)


def choice_probs(probs, n_plants):
    """Probability of each on/off choice (0 .. 2^n_plants - 1), summed over the slack qubits."""
    n_qubits = int(np.log2(len(probs)))
    return np.bincount(plant_index(n_plants, n_qubits), weights=probs, minlength=2 ** n_plants)

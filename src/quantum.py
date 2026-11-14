"""QAOA for one hour's QUBO (Milestone 4). Provided by the organizers; needs qiskit.

1. qubo_to_ising replaces each bit y with (1 - z)/2, which gives single-qubit Z terms
   and ZZ pair terms.
2. qaoa_circuit builds p layers: an rz on each qubit and an rzz on each pair (the cost
   layer), then an rx on each qubit (the mixer).
3. run_qaoa tunes the angles with COBYLA on the exact statevector (fast for 8 qubits).
   It minimizes the average energy, rescaled to the range 0 to 1.
4. choice_probs sums the probability over the slack qubits, giving the chance of each
   on/off choice.

Honesty note for the deck: to tune the angles, run_qaoa scores every bitstring first,
which already finds the best one. Count that classical work in your timing.
"""
import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit import ParameterVector
from qiskit.quantum_info import Statevector
from scipy.optimize import minimize

from src.qubo import all_energies, plant_index


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


def qaoa_circuit(Q, p=1):
    """Parameterized QAOA circuit with p layers. Returns (circuit, parameters)."""
    h, J = qubo_to_ising(Q)
    scale = max(np.abs(h).max(), max((abs(v) for v in J.values()), default=0.0))  # keeps angles sane
    gammas, betas = ParameterVector("gamma", p), ParameterVector("beta", p)
    qc = QuantumCircuit(len(Q))
    qc.h(range(len(Q)))
    for layer in range(p):
        for j, hj in enumerate(h):
            if hj != 0:
                qc.rz(2 * gammas[layer] * hj / scale, j)
        for (j, k), Jjk in J.items():
            qc.rzz(2 * gammas[layer] * Jjk / scale, j, k)
        qc.rx(2 * betas[layer], range(len(Q)))
    return qc, list(gammas) + list(betas)


def run_qaoa(Q, offset, p=1, start=None, maxiter=60):
    """Tune the angles on the exact statevector. Returns (angles, probabilities of all bitstrings)."""
    E = all_energies(Q, offset)
    E = (E - E.min()) / (E.max() - E.min())
    qc, params = qaoa_circuit(Q, p)

    def probs_at(angles):
        return Statevector(qc.assign_parameters(dict(zip(params, angles)))).probabilities()

    def average_energy(angles):
        return probs_at(angles) @ E

    if start is None or len(start) != 2 * p:     # coarse grid for one (gamma, beta), used in every layer
        grid = [(g, b) for g in np.linspace(0.1, 3.0, 15) for b in np.linspace(0.1, 1.5, 8)]
        g, b = min(grid, key=lambda gb: average_energy([gb[0]] * p + [gb[1]] * p))
        start = [g] * p + [b] * p
    result = minimize(average_energy, start, method="COBYLA", options={"maxiter": maxiter, "rhobeg": 0.2})
    return result.x, probs_at(result.x)


def choice_probs(probs, n_plants):
    """Probability of each on/off choice (0 .. 2^n_plants - 1), summed over the slack qubits."""
    n_qubits = int(np.log2(len(probs)))
    return np.bincount(plant_index(n_plants, n_qubits), weights=probs, minlength=2 ** n_plants)

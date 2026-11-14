"""QAOA on Max-Cut: the primer (part of Milestone 3). Two TODOs: the cost layer and the optimizer.

Split a small grid's substations into two groups so that as many lines as possible run
between the groups. It shows QAOA's three pieces, which come back in plant scheduling:
a cost layer, a mixer, and a classical optimizer that tunes them.

Deliverable for the deck: one sentence on what the cost layer, mixer and optimizer each
do, and how the Max-Cut cost relates to the unit-commitment QUBO.
"""
from itertools import product

import numpy as np
from scipy.optimize import minimize  # noqa: F401  (used by the optimizer TODO)

# 6-node grid (2 x 3) for Part 1
EDGES_SMALL = [(0, 1), (1, 2), (3, 4), (4, 5), (0, 3), (1, 4), (2, 5)]
N_SMALL = 6

# 12-node grid (3 x 4) for the optional GPU scale-up in Part 2
EDGES_LARGE = [(0, 1), (1, 2), (2, 3), (4, 5), (5, 6), (6, 7), (8, 9), (9, 10), (10, 11),
               (0, 4), (4, 8), (1, 5), (5, 9), (2, 6), (6, 10), (3, 7), (7, 11)]
N_LARGE = 12

_SIM = None


def simulator():
    global _SIM
    if _SIM is None:
        from qiskit_aer import AerSimulator
        _SIM = AerSimulator()
    return _SIM


def cut_value(bitstring, edges):
    """Count how many edges are cut by a 0/1 assignment (given as a string, node 0 first)."""
    bits = [int(b) for b in bitstring]
    return sum(1 for (u, v) in edges if bits[u] != bits[v])


# ---------------------------------------------------------------- TODO (primer): cost layer
def qaoa_circuit(params, n, edges, p):
    """Build a p-layer QAOA circuit. params = [gammas..., betas...]."""
    from qiskit import QuantumCircuit

    gammas = params[:p]
    betas = params[p:]
    qc = QuantumCircuit(n, n)
    qc.h(range(n))                    # start in equal superposition
    for layer in range(p):
        # --- Cost layer ---
        # TODO: for each edge (u, v), apply the Max-Cut cost rotation.
        # Hint: cx(u, v); rz(2 * gammas[layer], v); cx(u, v)
        # When your lines are in, delete the raise line below.
        raise NotImplementedError("Implement the cost layer")

        # --- Mixer layer (provided) ---
        for q in range(n):
            qc.rx(2 * betas[layer], q)
    qc.measure(range(n), range(n))
    return qc


def expected_cut(params, n, edges, p, shots=512):
    """Run the circuit and return the AVERAGE cut value (we maximize this)."""
    from qiskit import transpile

    sim = simulator()
    qc = qaoa_circuit(params, n, edges, p)
    counts = sim.run(transpile(qc, sim), shots=shots).result().get_counts()
    total = sum(counts.values())
    # bitstrings come back reversed in Qiskit; reverse to match node order
    return sum(cut_value(bs[::-1], edges) * c for bs, c in counts.items()) / total


# ---------------------------------------------------------------- TODO (primer): optimizer
def optimize(n, edges, p=1):
    """Tune the QAOA angles. Returns a scipy OptimizeResult (use result.x for the angles).

    We minimize the NEGATIVE average cut.
    """
    def objective(params):
        return -expected_cut(params, n, edges, p)

    # TODO: choose a starting point and call scipy.optimize.minimize.
    # Hint: x0 = np.random.rand(2 * p); result = minimize(objective, x0, method="COBYLA")
    # One random start often stalls on a poor answer. Try a few starts and keep the best one.
    # When your lines are in, delete the raise line below.
    raise NotImplementedError("Run the optimizer, then read out the best partition")


# ---------------------------------------------------------------- provided
def read_out(params, n, edges, p, shots=2048):
    """Sample the tuned circuit. Returns (best_bits, group_A, group_B, best_cut, average_cut)."""
    from qiskit import transpile

    sim = simulator()
    qc = qaoa_circuit(params, n, edges, p)
    counts = sim.run(transpile(qc, sim), shots=shots).result().get_counts()
    # Of the bitstrings QAOA sampled, keep the one with the biggest cut (reverse: qubit 0 is last).
    best_bits = max((bs[::-1] for bs in counts), key=lambda b: cut_value(b, edges))
    group_a = [i for i, b in enumerate(best_bits) if b == "0"]
    group_b = [i for i, b in enumerate(best_bits) if b == "1"]
    # The best of 2,048 samples finds the best cut even by random guessing on a grid this small,
    # so also compare the AVERAGE cut per shot with random guessing (len(edges) / 2).
    avg = sum(cut_value(bs[::-1], edges) * c for bs, c in counts.items()) / sum(counts.values())
    return best_bits, group_a, group_b, cut_value(best_bits, edges), avg


def brute_force(n, edges):
    """Classical baseline: best cut by checking every assignment. Fine up to about 20 nodes."""
    best_cut, best = -1, None
    for assign in product([0, 1], repeat=n):
        c = cut_value("".join(map(str, assign)), edges)
        if c > best_cut:
            best_cut, best = c, assign
    return best_cut, best


def random_average_cut(edges):
    """Random guessing cuts each line half the time."""
    return len(edges) / 2

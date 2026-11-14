"""One hour of unit commitment as a QUBO (Milestone 3): TODO 2 and TODO 3, plus helpers.

Qubits for one hour (5-plant fleet, 8 qubits):
    0 .. n-1          x_i = 1 if plant i is on
    n .. n+n_slack-1  slack bits s_0, s_1, s_2 for the safety-margin (reserve) rule

Energy to minimize:
    E = sum_i c_i x_i + A * ( sum_i a_i x_i - (s_0 + 2 s_1 + 4 s_2) - r )^2

    c_i  cost of having plant i on this hour (TODO 2)
    a_i  plant i's capacity in 50 MW blocks (pmax_i / 50)
    r    blocks needed this hour = ceil((demand + reserve) / 50)
    A    penalty weight, default 2 * max_i c_i

Storage convention for (Q, offset):
    energy(y) = sum_j Q[j, j] y_j + sum_{j<k} Q[j, k] y_j y_k + offset
The diagonal holds single terms, the upper triangle holds pair terms, the lower
triangle is unused.

Bit convention: bit j of an integer index = qubit j. index_bits(n_qubits)[k] holds
the bits of index k, so you never reverse a Qiskit bitstring by hand.
"""
from functools import lru_cache

import numpy as np

from src.config import BLOCK_MW, N_SLACK


# ---------------------------------------------------------------- TODO 2
def plant_hour_costs(plants, was_on):
    """c[i] = approximate cost in $ of having plant i on for this hour.

        c_i = startup_i * (1 - was_on_i) + no_load_i + pmin_i * (marginal_i - marginal_cheapest)

    Why: a plant that is on must make at least pmin MW. The rest of the demand comes
    from the cheapest plant with room to spare (COAL, whenever it has room), whichever
    plants you pick. So what plant i adds is its startup (only if it was off last
    hour), its no-load cost, and its extra price on those pmin MW.

    This is an approximation: it ignores who makes the last MW when COAL is already
    full. The checker uses the exact cost, so you can measure how often it picks the
    true best (improving it is a stretch goal).

    was_on[i] is 1 if plant i was on in the previous hour. marginal_cheapest is the
    smallest marginal_cost_per_mwh in the fleet.
    """
    c = np.zeros(len(plants))
    # TODO 2: fill c[i] with the formula above.
    # When your lines are in, delete the raise line below.
    raise NotImplementedError("TODO 2: the cost of each plant for one hour")
    return c


# ---------------------------------------------------------------- TODO 3
def build_qubo(plants, demand_mw, reserve_mw, was_on, penalty=None, n_slack=N_SLACK):
    """QUBO for one hour. Returns (Q, offset).

    Hint: put all bits in one list y = (x_0, ..., x_{n-1}, s_0, s_1, s_2) with weights
    b = (a_0, ..., a_{n-1}, -1, -2, -4). The bracket is then sum_j b_j y_j - r.
    Because y_j^2 = y_j for 0/1 bits,

        (sum_j b_j y_j - r)^2 = sum_j (b_j^2 - 2 r b_j) y_j + sum_{j<k} 2 b_j b_k y_j y_k + r^2

    1. Cost part: add c[i] to Q[i, i] for each plant.
    2. Penalty part: multiply each term of the expansion by A and add it to the right
       place: single terms on the diagonal, pair terms at Q[j, k] with j < k, the
       constant to offset.

    b and r are computed for you.
    """
    c = plant_hour_costs(plants, was_on)
    A = 2 * c.max() if penalty is None else penalty
    b = capacity_weights(plants, n_slack)
    r = blocks_needed(demand_mw, reserve_mw)
    n_qubits = len(plants) + n_slack
    Q = np.zeros((n_qubits, n_qubits))
    offset = 0.0
    # TODO 3: add the cost part and the penalty part to Q and offset.
    # When your lines are in, delete the raise line below.
    raise NotImplementedError("TODO 3: build the QUBO")
    return Q, offset


# ---------------------------------------------------------------- provided helpers
def capacity_weights(plants, n_slack=N_SLACK):
    """b = (pmax_i / 50 for each plant) + (-1, -2, -4, ...) for the slack bits."""
    return np.array([p["pmax_mw"] / BLOCK_MW for p in plants] + [-(2 ** k) for k in range(n_slack)])


def blocks_needed(demand_mw, reserve_mw):
    """r = ceil((demand + reserve) / 50): 50 MW blocks the hour needs."""
    return float(np.ceil((demand_mw + reserve_mw) / BLOCK_MW))


def add_locks(Q, offset, must_on, must_off, weight):
    """Penalty weight*(1 - x_i) for a plant that must stay on, weight*x_i for one that must stay off."""
    Q = Q.copy()
    for i in must_on:
        Q[i, i] -= weight
        offset += weight
    for i in must_off:
        Q[i, i] += weight
    return Q, offset


@lru_cache(maxsize=None)
def index_bits(n_qubits):
    """Row k holds the n_qubits bits of integer index k (bit j = qubit j)."""
    return (np.arange(2 ** n_qubits)[:, None] >> np.arange(n_qubits)) & 1


@lru_cache(maxsize=None)
def plant_index(n_plants, n_qubits):
    """For every bitstring index, the on/off choice (0 .. 2^n_plants - 1) in its low bits."""
    return index_bits(n_qubits)[:, :n_plants] @ (2 ** np.arange(n_plants))


def all_energies(Q, offset):
    """QUBO energy of every bitstring (2^n_qubits of them)."""
    bits = index_bits(len(Q))
    U = np.triu(Q)
    return np.einsum("bj,jk,bk->b", bits, U, bits) + offset


def brute_force_qubo(Q, offset):
    """Cheapest bitstring of the QUBO by checking all of them. Returns (bits, energy)."""
    E = all_energies(Q, offset)
    k = int(np.argmin(E))
    return index_bits(len(Q))[k], E[k]


def choice_to_index(choice):
    """List of 0/1 per plant -> integer index (bit i = plant i)."""
    return int(np.dot(np.asarray(choice, dtype=int), 2 ** np.arange(len(choice))))


def index_to_choice(k, n_plants):
    """Integer index -> list of 0/1 per plant."""
    return [(int(k) >> i) & 1 for i in range(n_plants)]


def label(choice, names):
    """Plant names for an on/off choice given as an integer index or a list of 0/1."""
    on = index_to_choice(choice, len(names)) if np.isscalar(choice) else choice
    return "+".join(n for n, u in zip(names, on) if u) or "none"

"""Unit-commitment scenarios that are known to be hard for LP-based branch and bound (MILP).

Each generator returns an Instance that holds the SAME problem twice:
  - as a MILP (scipy.optimize.milp data: c, A, lo, hi, integrality, upper bounds), and
  - as a QUBO (Q, offset) in the storage convention of src/qubo.py
    (energy(y) = sum_j Q[j,j] y_j + sum_{j<k} Q[j,k] y_j y_k + offset, lower triangle unused).
One qubit per plant, no slack qubits: every family uses equality constraints, so the penalty is a
plain square. The QUBO minimum equals the MILP optimum (tests/test_hard_instances.py checks it).

Families (all one hour, n plants, costs in $k so every energy is an integer):

market_split  "Must-take, no curtailment": m zones (or m hours) where the committed plants' output
              must equal the zone's demand exactly. Block sizes 0..99 per zone; demand comes from a
              planted on/off choice with about half the plants on, so a solution exists. This is the
              Cornuejols-Dawande market-split family: small 0-1 programs that are very hard for
              branch and bound. Cost: sum c_i x_i.
interaction   "Pairwise costs": a shared gas pipeline, shared start-up crews and transmission paths
              make the cost of running two plants together differ from the sum of their costs:
              sum c_i x_i + sum_{i<j} W_ij x_i x_j with W of mixed sign (nonconvex). Exactly k plants
              (equal-size units) must run. QUBO handles W natively; the MILP needs a linearized product
              variable per pair, whose LP bound is weak.
symmetric     "Fleet of identical units": three unit types (2, 3 and 5 blocks), many identical copies
              of each, demand to be matched exactly. Very many equivalent optimal schedules.
"""
from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import csr_matrix

FAMILIES = ("market_split", "interaction", "symmetric")


@dataclass
class Instance:
    family: str
    n: int                      # plants = qubits = MILP binaries
    seed: int
    Q: np.ndarray               # QUBO, upper-triangular storage
    offset: float
    c: np.ndarray               # MILP objective
    A: csr_matrix               # MILP constraint rows: lo <= A x <= hi
    lo: np.ndarray
    hi: np.ndarray
    integrality: np.ndarray
    upper: np.ndarray
    meta: dict = field(default_factory=dict)

    @property
    def n_qubits(self):
        return len(self.Q)

    def objective(self, x):
        """True cost of on/off choice x (plants only), ignoring feasibility."""
        x = np.asarray(x, dtype=float)
        cost = float(self.meta["cost"] @ x)
        W = self.meta.get("W")
        if W is not None:
            cost += float(x @ np.triu(W, 1) @ x)
        return cost

    def feasible(self, x):
        x = np.asarray(x, dtype=float)
        rows, rhs = self.meta["eq_rows"], self.meta["eq_rhs"]
        return bool(np.all(np.abs(rows @ x - rhs) < 1e-9))

    def energy(self, x):
        y = np.asarray(x, dtype=float)
        return float(y @ np.triu(self.Q) @ y + self.offset)


def penalty_qubo(cost, rows, rhs, A_pen, W=None):
    """QUBO for  cost.x + x'triu(W)x + A_pen * sum_r (rows[r].x - rhs[r])^2,  using x^2 = x."""
    n = len(cost)
    Q = np.zeros((n, n))
    Q[np.diag_indices(n)] += cost
    if W is not None:
        Q += np.triu(W, 1)
    offset = 0.0
    for a, r in zip(rows, rhs):
        Q[np.diag_indices(n)] += A_pen * (a ** 2 - 2 * r * a)
        Q += A_pen * np.triu(2 * np.outer(a, a), 1)
        offset += A_pen * r ** 2
    return Q, offset


def _linear_instance(family, n, seed, cost, rows, rhs, A_pen, meta):
    rows, rhs = np.asarray(rows, dtype=float), np.asarray(rhs, dtype=float)
    Q, offset = penalty_qubo(cost, rows, rhs, A_pen)
    meta = dict(meta, cost=cost, eq_rows=rows, eq_rhs=rhs, penalty=A_pen)
    return Instance(family, n, seed, Q, offset, c=cost.astype(float), A=csr_matrix(rows), lo=rhs, hi=rhs,
                    integrality=np.ones(n), upper=np.ones(n), meta=meta)


def market_split(n, seed=0, m=None):
    """m zones (default max(2, 1 + n // 10)), block sizes 0..99, planted solution with about n/2 plants on."""
    rng = np.random.default_rng([1, n, seed])
    m = max(2, 1 + n // 10) if m is None else m
    a = rng.integers(0, 100, size=(m, n))
    planted = np.zeros(n, dtype=int)
    planted[rng.choice(n, n // 2, replace=False)] = 1
    rhs = a @ planted
    cost = rng.integers(1, 11, size=n).astype(float)
    A_pen = cost.sum() + 1          # any infeasible x is >= 1 away in some row: penalty beats any saving
    return _linear_instance("market_split", n, seed, cost, a, rhs, A_pen, dict(m=m, planted=planted))


def symmetric(n, seed=0):
    """Three unit types (2, 3, 5 blocks; cost 7, 10, 16 $k), each plant's type drawn at random,
    demand from a planted half-fleet."""
    rng = np.random.default_rng([3, n, seed])
    types = rng.integers(0, 3, size=n)
    size = np.array([2, 3, 5])[types]
    cost = np.array([7.0, 10.0, 16.0])[types]
    planted = np.zeros(n, dtype=int)
    planted[rng.choice(n, n // 2, replace=False)] = 1
    rhs = [int(size @ planted)]
    A_pen = cost.sum() + 1
    return _linear_instance("symmetric", n, seed, cost, [size], rhs, A_pen, dict(m=1, planted=planted))


def interaction(n, seed=0, k=None):
    """sum c_i x_i + sum_{i<j} W_ij x_i x_j, exactly k = n // 2 plants on. W_ij in -10..10 (dense)."""
    rng = np.random.default_rng([2, n, seed])
    k = n // 2 if k is None else k
    cost = rng.integers(0, 21, size=n).astype(float)
    W = np.triu(rng.integers(-10, 11, size=(n, n)), 1).astype(float)
    W = W + W.T
    # Flipping one bit changes the cost by at most M; an x with |sum x - k| = d can be repaired with
    # d flips, so a penalty A > M makes every infeasible x dearer than some feasible one.
    M = np.max(np.abs(cost) + np.abs(W).sum(axis=1))
    A_pen = M + 1
    ones = np.ones((1, n))
    Q, offset = penalty_qubo(cost, ones, [k], A_pen, W=W)

    # MILP: x (n binaries) + y_ij (continuous, one per pair with W_ij != 0) for the product x_i x_j.
    # Minimizing: W_ij > 0 needs only y >= x_i + x_j - 1, y >= 0; W_ij < 0 needs only y <= x_i, y <= x_j.
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n) if W[i, j] != 0]
    nv = n + len(pairs)
    c = np.r_[cost, [W[i, j] for i, j in pairs]]
    rows, lo, hi = [], [], []
    r = np.zeros(nv)
    r[:n] = 1
    rows.append(r); lo.append(k); hi.append(k)
    for p, (i, j) in enumerate(pairs):
        y = n + p
        if W[i, j] > 0:
            r = np.zeros(nv); r[y], r[i], r[j] = 1, -1, -1
            rows.append(r); lo.append(-1); hi.append(np.inf)
        else:
            for v in (i, j):
                r = np.zeros(nv); r[y], r[v] = 1, -1
                rows.append(r); lo.append(-np.inf); hi.append(0)
    meta = dict(cost=cost, W=W, k=k, eq_rows=ones, eq_rhs=np.array([k], dtype=float), penalty=A_pen,
                pairs=len(pairs))
    return Instance("interaction", n, seed, Q, offset, c=c, A=csr_matrix(np.array(rows)), lo=np.array(lo, float),
                    hi=np.array(hi, float), integrality=np.r_[np.ones(n), np.zeros(len(pairs))],
                    upper=np.ones(nv), meta=meta)


GENERATORS = {"market_split": market_split, "interaction": interaction, "symmetric": symmetric}


def make(family, n, seed=0):
    return GENERATORS[family](n, seed)

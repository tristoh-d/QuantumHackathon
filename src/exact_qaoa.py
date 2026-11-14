"""Exact, noise-free QAOA for a QUBO, in numpy (no shots, no noise).

The circuit is the same as src/quantum.qaoa_circuit: H on every qubit, then p layers of
(cost layer from the Ising form of Q, scaled by its largest coefficient) and (rx(2 beta) on every qubit).
Because the cost layer is diagonal, it is applied as one elementwise phase exp(-i gamma E / scale), which
equals the rz / rzz gates up to a global phase. The mixer is applied qubit by qubit on the 2^n state.
The result is the exact probability of every bitstring, so the chance of sampling the optimum is computed,
not estimated. Memory: 16 bytes x 2^n (64 MB at 22 qubits).

Bit convention as in src/qubo.py: bit j of a bitstring index = qubit j.

Honesty note (as in src/quantum.py): tuning the angles uses every bitstring's energy, which already
reveals the optimum. Its time is reported separately as classical tuning time.
"""
import time
from functools import reduce

import numpy as np
from scipy.optimize import minimize


def energies(Q, offset=0.0):
    """Energy of all 2^n bitstrings, built one qubit at a time (O(n 2^n) time, no 2^n x n bit table)."""
    n = len(Q)
    U = np.triu(Q)
    E = np.array([0.0])
    for j in range(n):
        size = len(E)
        idx = np.arange(size)
        lin = np.full(size, U[j, j])
        for k in range(j):
            if U[k, j] != 0:
                lin += U[k, j] * ((idx >> k) & 1)
        E = np.concatenate([E, E + lin])
    return E + offset


def ising_scale(Q):
    """Largest |h| or |J| of the Ising form, as in src/quantum.qaoa_circuit."""
    from src.quantum import qubo_to_ising
    h, J = qubo_to_ising(Q)
    return max(np.abs(h).max(), max((abs(v) for v in J.values()), default=0.0))


def ising_scale_fast(Q):
    """Same value as ising_scale without building the dict (for large n)."""
    U = np.triu(Q, 1)
    h = -np.diag(Q) / 2 - (U.sum(axis=1) + U.sum(axis=0)) / 4
    return max(np.abs(h).max(), np.abs(U).max() / 4)


def _mix(psi, beta, n, block=5):
    """rx(2 beta) on every qubit. Qubits are taken 5 at a time: one 32 x 32 matrix (the Kronecker product
    of five rx gates) multiplies the state reshaped to (high, 32, low). About 9x faster than one qubit at a time."""
    c, s = np.cos(beta), -1j * np.sin(beta)
    rx = np.array([[c, s], [s, c]])
    j = 0
    while j < n:
        w = min(block, n - j)
        M = reduce(np.kron, [rx] * w)
        psi = np.matmul(M[None], psi.reshape(2 ** (n - j - w), 2 ** w, 2 ** j)).reshape(-1)
        j += w
    return psi


def state(E_scaled, angles, n):
    """Exact QAOA state. E_scaled = energies / ising scale; angles = gammas (p) + betas (p)."""
    p = len(angles) // 2
    psi = np.full(2 ** n, 2 ** (-n / 2), dtype=complex)
    for layer in range(p):
        psi *= np.exp(-1j * angles[layer] * E_scaled)
        psi = _mix(psi, angles[p + layer], n)
    return psi


def probs(E_scaled, angles, n):
    return np.abs(state(E_scaled, angles, n)) ** 2


class Problem:
    """Precomputed energies for one QUBO."""

    def __init__(self, Q, offset=0.0, E=None):
        self.n = len(Q)
        self.E = energies(Q, offset) if E is None else E
        self.scale = ising_scale_fast(Q)
        self.E_scaled = self.E / self.scale
        self.e_min, self.e_max = self.E.min(), self.E.max()
        self.E_norm = (self.E - self.e_min) / (self.e_max - self.e_min)
        self.opt_mask = np.isclose(self.E, self.e_min, rtol=0, atol=1e-6)

    def probs(self, angles):
        return probs(self.E_scaled, angles, self.n)

    def mean_energy(self, angles):
        return self.probs(angles) @ self.E_norm

    def p_opt(self, angles):
        return float(self.probs(angles)[self.opt_mask].sum())

    def stats(self, angles, feasible_mask=None):
        """Exact p_opt, approximation ratio of the mean energy (1 = always optimal), p_feasible."""
        pr = self.probs(angles)
        mean = pr @ self.E
        out = dict(p_opt=float(pr[self.opt_mask].sum()),
                   mean_norm=float(pr @ self.E_norm))
        if feasible_mask is not None:
            out["p_feasible"] = float(pr[feasible_mask].sum())
        out["mean_energy"] = float(mean)
        return out


def tune(prob: Problem, p=1, start=None, maxiter=80, grid=(12, 6)):
    """Minimize the mean (normalized) energy. Returns (angles, seconds).

    p=1 without start: coarse grid over (gamma, beta), then COBYLA. For p>1 pass the p-1 angles as
    `start`; they are extended by repeating the last layer (a standard warm start).
    """
    t0 = time.perf_counter()
    if start is None:
        gs = np.linspace(0.05, np.pi, grid[0])
        bs = np.linspace(0.05, np.pi / 2, grid[1])
        g, b = min(((g, b) for g in gs for b in bs), key=lambda gb: prob.mean_energy([gb[0]] * p + [gb[1]] * p))
        start = [g] * p + [b] * p
    elif len(start) != 2 * p:
        q = len(start) // 2
        gam, bet = list(start[:q]), list(start[q:])
        gam += [gam[-1]] * (p - q)
        bet += [bet[-1]] * (p - q)
        start = gam + bet
    res = minimize(prob.mean_energy, start, method="COBYLA", options={"maxiter": maxiter, "rhobeg": 0.2})
    return np.asarray(res.x), time.perf_counter() - t0


def tts99(p_success):
    """Repetitions needed for a 99% chance of at least one success."""
    if p_success <= 0:
        return np.inf
    if p_success >= 1:
        return 1.0
    return float(np.log(0.01) / np.log1p(-p_success))

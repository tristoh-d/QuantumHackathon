"""Simulated annealing (SA) on a QUBO: the classical-heuristic baseline for QAOA.

Many independent runs at once (numpy, vectorized over runs). Each run starts from a random bitstring
and does `sweeps` sweeps; one sweep proposes a flip of every bit in turn with the Metropolis rule.
The temperature falls geometrically from T_hot to T_cold, both set from the QUBO's own flip costs:
T_hot accepts a typical uphill flip with probability 1/2, T_cold accepts the smallest uphill
flip with probability about 1% (or, with energy_unit, a flip of one energy unit).
"""
import time

import numpy as np


def _sym(Q):
    U = np.triu(Q, 1)
    return np.diag(Q).copy(), U + U.T


def temperatures(Q, rng, samples=200, energy_unit=None):
    d, S = _sym(Q)
    x = rng.integers(0, 2, size=(samples, len(Q))).astype(float)
    delta = np.abs((1 - 2 * x) * (d + x @ S))
    pos = delta[delta > 1e-9]
    if len(pos) == 0:
        return 1.0, 0.01
    t_hot = np.median(pos) / np.log(2)
    t_cold = pos.min() / np.log(100)
    if energy_unit is not None:         # smallest possible uphill step is known (integer energies: 1)
        t_cold = energy_unit / np.log(100)
    return t_hot, min(t_cold, t_hot)


def anneal(Q, offset=0.0, runs=1000, sweeps=100, seed=0, energy_unit=None):
    """Returns (final bitstrings [runs x n], final energies [runs], seconds per run).

    energy_unit: the smallest energy difference that matters (1 for the integer instances in
    src/hard_instances.py). Without it T_cold comes from sampled flip costs, which can be far too hot
    when a big penalty dominates every flip.
    """
    rng = np.random.default_rng(seed)
    d, S = _sym(Q)
    n = len(Q)
    t_hot, t_cold = temperatures(Q, rng, energy_unit=energy_unit)
    temps = t_hot * (t_cold / t_hot) ** (np.arange(sweeps) / max(1, sweeps - 1))
    t0 = time.perf_counter()
    x = rng.integers(0, 2, size=(runs, n)).astype(float)
    field = d + x @ S                           # field[r, i] = d_i + sum_j S_ij x_j
    for T in temps:
        for i in range(n):
            dE = (1 - 2 * x[:, i]) * field[:, i]
            flip = (dE <= 0) | (rng.random(runs) < np.exp(-np.maximum(dE, 0) / T))
            if flip.any():
                step = np.where(flip, 1 - 2 * x[:, i], 0.0)     # +1 for 0->1, -1 for 1->0
                x[:, i] += step
                field += step[:, None] * S[i][None, :]
    seconds = (time.perf_counter() - t0) / runs
    E = np.einsum("ri,ij,rj->r", x, np.triu(Q), x) + offset
    return x.astype(int), E, seconds

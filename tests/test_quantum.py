"""The provided QAOA pieces and the hour-by-hour loop. QAOA tests need qiskit; loop tests need TODOs 2 and 3."""
import numpy as np
import pytest

from src.qubo import all_energies, index_bits
from src.scheduler import run_day
from tests.conftest import call_or_skip


def random_qubo(n=5, seed=0):
    rng = np.random.default_rng(seed)
    return np.triu(rng.normal(size=(n, n))), float(rng.normal())


def test_index_bits_convention():
    bits = index_bits(3)
    assert list(bits[1]) == [1, 0, 0] and list(bits[4]) == [0, 0, 1]


def test_qubo_to_ising_preserves_energy_differences():
    pytest.importorskip("qiskit")
    from src.quantum import qubo_to_ising
    Q, offset = random_qubo()
    h, J = qubo_to_ising(Q)
    z = 1 - 2 * index_bits(len(Q))                 # y = (1 - z) / 2
    ising = z @ h + sum(v * z[:, j] * z[:, k] for (j, k), v in J.items())
    E = all_energies(Q, offset)
    np.testing.assert_allclose(E - E[0], ising - ising[0], atol=1e-9)


def test_run_qaoa_returns_distribution():
    pytest.importorskip("qiskit")
    from src.quantum import choice_probs, run_qaoa
    Q, offset = random_qubo(6)
    angles, probs = run_qaoa(Q, offset, p=1, maxiter=10)
    assert len(angles) == 2 and probs.shape == (64,)
    assert probs.sum() == pytest.approx(1.0)
    assert choice_probs(probs, 4).sum() == pytest.approx(1.0)


def test_random_day_runs(problem, milp):
    r = call_or_skip(run_day, problem, milp["cost"], sampler="random", shots=50, seed=0)
    assert r["schedule"].shape == (24, problem.n) and len(r["log"]) == 24


@pytest.mark.slow
def test_qaoa_day_runs(problem, milp):
    pytest.importorskip("qiskit")
    r = call_or_skip(run_day, problem, milp["cost"], sampler="qaoa", shots=50, seed=0, maxiter=10)
    assert r["schedule"].shape == (24, problem.n)

"""MILP-hard scenario families: QUBO and MILP agree, the exact QAOA simulator matches Qiskit, SA works."""
import numpy as np
import pytest

from src import anneal, exact_qaoa as eq, hard_instances as hi, hard_milp
from src.qubo import all_energies


@pytest.mark.parametrize("family", hi.FAMILIES)
@pytest.mark.parametrize("n", [6, 9])
def test_qubo_minimum_equals_milp_optimum(family, n):
    for seed in range(3):
        inst = hi.make(family, n, seed)
        E = eq.energies(inst.Q, inst.offset)
        k = int(E.argmin())
        x = (k >> np.arange(n)) & 1
        milp = hard_milp.solve(inst)
        assert milp["cost"] == pytest.approx(E.min(), abs=1e-6)
        assert inst.feasible(x)
        assert inst.objective(x) == pytest.approx(E.min())
        assert inst.feasible(milp["x"]) and inst.objective(milp["x"]) == pytest.approx(milp["cost"], abs=1e-6)


@pytest.mark.parametrize("family", hi.FAMILIES)
def test_qubo_energy_is_objective_plus_penalty(family):
    inst = hi.make(family, 7, 1)
    E = eq.energies(inst.Q, inst.offset)
    rows, rhs, A = inst.meta["eq_rows"], inst.meta["eq_rhs"], inst.meta["penalty"]
    for k in range(2 ** 7):
        x = (k >> np.arange(7)) & 1
        assert E[k] == pytest.approx(inst.objective(x) + A * np.sum((rows @ x - rhs) ** 2))


def test_generators_are_deterministic():
    for fam in hi.FAMILIES:
        a, b = hi.make(fam, 10, 3), hi.make(fam, 10, 3)
        assert np.array_equal(a.Q, b.Q) and a.offset == b.offset


def test_energies_match_qubo_module():
    inst = hi.make("interaction", 10, 0)
    assert np.allclose(eq.energies(inst.Q, inst.offset), all_energies(inst.Q, inst.offset))


def test_ising_scale_fast_matches_quantum_module():
    for fam in hi.FAMILIES:
        Q = hi.make(fam, 8, 0).Q
        assert eq.ising_scale_fast(Q) == pytest.approx(eq.ising_scale(Q))


@pytest.mark.parametrize("p", [1, 2])
def test_exact_qaoa_matches_qiskit_statevector(p):
    from qiskit.quantum_info import Statevector

    from src.quantum import qaoa_circuit
    inst = hi.make("interaction", 7, 2)
    P = eq.Problem(inst.Q, inst.offset)
    angles = np.linspace(0.3, 1.1, 2 * p)
    qc, params = qaoa_circuit(inst.Q, p)
    ref = Statevector(qc.assign_parameters(dict(zip(params, angles)))).probabilities()
    assert np.allclose(P.probs(angles), ref, atol=1e-12)


def test_tuned_qaoa_beats_uniform_on_mean_energy():
    inst = hi.make("symmetric", 8, 0)
    P = eq.Problem(inst.Q, inst.offset)
    angles, _ = eq.tune(P, 1)
    assert P.mean_energy(angles) < P.E_norm.mean()
    assert P.probs(angles).sum() == pytest.approx(1.0)


def test_anneal_finds_optimum_on_small_instance():
    inst = hi.make("interaction", 8, 0)
    e_min = eq.energies(inst.Q, inst.offset).min()
    x, E, _ = anneal.anneal(inst.Q, inst.offset, runs=200, sweeps=200, energy_unit=1.0)
    assert np.isclose(E, e_min).any()
    assert np.allclose(E, [inst.energy(r) for r in x])


def test_tts99():
    assert eq.tts99(1.0) == 1.0
    assert eq.tts99(0.0) == np.inf
    assert eq.tts99(0.5) == pytest.approx(np.log(0.01) / np.log(0.5))

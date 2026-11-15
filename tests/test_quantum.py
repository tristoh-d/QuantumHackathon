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


# ---------------------------------------------------------------- circuit and qubit-count optimizations
def _unitary(qc, params, angles):
    from qiskit.quantum_info import Operator
    return Operator(qc.assign_parameters(dict(zip(params, angles)))).data


@pytest.mark.parametrize("n, p", [(4, 1), (6, 2)])
def test_phase_poly_circuit_is_the_same_unitary(n, p):
    pytest.importorskip("qiskit")
    from src.quantum import qaoa_circuit
    Q, _ = random_qubo(n, seed=n)
    angles = np.linspace(0.2, 1.3, 2 * p)
    U_pairs = _unitary(*qaoa_circuit(Q, p, synthesis="pairs"), angles)
    U_poly = _unitary(*qaoa_circuit(Q, p, synthesis="phase_poly"), angles)
    k = np.unravel_index(np.abs(U_pairs).argmax(), U_pairs.shape)
    phase = U_poly[k] / U_pairs[k]                  # equal up to a global phase
    np.testing.assert_allclose(U_poly, phase * U_pairs, atol=1e-9)


def test_phase_poly_uses_fewer_cx():
    pytest.importorskip("qiskit")
    from qiskit import transpile

    from src.quantum import qaoa_circuit
    Q, _ = random_qubo(8, seed=1)

    def cx(synthesis):
        qc, params = qaoa_circuit(Q, 1, synthesis=synthesis)
        qc = qc.assign_parameters(dict(zip(params, [0.5, 0.4])))
        return transpile(qc, basis_gates=["rz", "sx", "x", "cx"], optimization_level=3).count_ops()["cx"]
    assert cx("phase_poly") < cx("pairs") == 56


@pytest.mark.parametrize("synthesis", ["pairs", "phase_poly"])
def test_numpy_state_matches_qiskit_circuit(synthesis):
    """run_qaoa's numpy state gives the same probabilities as the circuit sent to hardware."""
    pytest.importorskip("qiskit")
    from qiskit.quantum_info import Statevector

    from src.quantum import _numpy_probs, ising_scale, qaoa_circuit, qubo_to_ising
    Q, offset = random_qubo(6, seed=3)
    angles = [0.4, 0.7, 0.3, 0.2]
    qc, params = qaoa_circuit(Q, 2, synthesis=synthesis)
    ref = Statevector(qc.assign_parameters(dict(zip(params, angles)))).probabilities()
    E_scaled = all_energies(Q, offset) / ising_scale(*qubo_to_ising(Q))
    np.testing.assert_allclose(_numpy_probs(E_scaled, angles, 6), ref, atol=1e-10)


def test_reduce_qubo_keeps_energies():
    from src.quantum import reduce_qubo
    Q, offset = random_qubo(7, seed=4)
    fixed = {1: 1, 4: 0, 6: 1}
    Qs, offset_s, keep = reduce_qubo(Q, offset, fixed)
    assert keep == [0, 2, 3, 5]
    E, Es, bits = all_energies(Q, offset), all_energies(Qs, offset_s), index_bits(7)
    agrees = np.all([bits[:, j] == v for j, v in fixed.items()], axis=0)
    small_index = sum(bits[:, q] << i for i, q in enumerate(keep))
    np.testing.assert_allclose(E[agrees], Es[small_index[agrees]], atol=1e-9)


def test_embed_probs_puts_fixed_bits_back():
    from src.quantum import embed_probs
    probs = embed_probs(np.array([0.1, 0.2, 0.3, 0.4]), keep=[0, 2], fixed={1: 1, 3: 0}, n_qubits=4)
    assert probs.sum() == pytest.approx(1.0)
    assert np.flatnonzero(probs).tolist() == [0b0010, 0b0011, 0b0110, 0b0111]


def test_fixed_bits_keep_every_allowed_choice_at_its_best_energy(problem):
    """For each hour of a real day: every choice that keeps the locks has the same lowest energy (over the
    slack bits) in the reduced QUBO as in the full one, so removing qubits does not change the landscape."""
    from src.check import hour_ok
    from src.quantum import fixed_bits, reduce_qubo
    from src.qubo import add_locks, build_qubo, plant_index
    r = call_or_skip(run_day, problem, None, sampler="random", shots=200, seed=0, reduce=False)
    n = problem.n
    for entry in r["log"]:
        t, was_on = entry["hour"], entry["was_on"]
        Q, offset = build_qubo(problem.plants, problem.demand[t], problem.reserve[t], was_on)
        Q, offset = add_locks(Q, offset, entry["must_on"], entry["must_off"], weight=10.0)
        fixed = fixed_bits(problem.plants, problem.demand[t], problem.reserve[t],
                           entry["must_on"], entry["must_off"], problem.n_slack)
        Qs, offset_s, keep = reduce_qubo(Q, offset, fixed)
        E_full = all_energies(Q, offset)
        E_small = all_energies(Qs, offset_s)
        full_idx = sum(1 << j for j, v in fixed.items() if v) + \
            sum(((np.arange(len(E_small)) >> i) & 1) << q for i, q in enumerate(keep))
        pidx_full, pidx_small = plant_index(n, len(Q)), full_idx & (2 ** n - 1)
        for k in range(2 ** n):
            choice = [(k >> i) & 1 for i in range(n)]
            if not hour_ok(problem.plants, problem.demand[t], problem.reserve[t], choice,
                           entry["must_on"], entry["must_off"]):
                continue
            assert E_small[pidx_small == k].min() == pytest.approx(E_full[pidx_full == k].min()), (t, choice)


def test_expand_key_round_trip():
    from src.hardware import choice_shares, expand_key
    layout = {"keep": [0, 2, 3], "fixed": {1: 1, 4: 0}, "n_qubits": 5}
    assert expand_key("101", layout) == 0b01011         # measured q0=1, q1=0, q2=1 -> qubits 0, 3 on; qubit 1 fixed on
    assert expand_key("00000", layout) == 0             # older full-size circuit: read as is
    share = choice_shares({"101": 3, "000": 1}, 3, layout)
    assert share[0b011] == pytest.approx(0.75) and share[0b010] == pytest.approx(0.25)

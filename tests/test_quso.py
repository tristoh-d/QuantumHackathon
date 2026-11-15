"""The QPE / HHL approach (arXiv:2305.08482): grid model, HHL, amplitude estimation, QuSO cost layer, network MILP.

Each test checks a quantum piece against the exact classical answer it should reproduce.
"""
from dataclasses import replace

import numpy as np
import pytest

from src.config import load_problem
from src.network import (BASE_MVA, hour_network, injections_mw, load_network, p_bar_pu, plant_areas,
                         solve_angles)
from src.qubo import index_to_choice

pytest.importorskip("qiskit")

HOUR = 14          # an afternoon hour: COAL + GAS_CC are both needed
VALID = (3, 11)    # COAL+GAS_CC and COAL+GAS_CC+PEAKER_B (the valid choices that differ in network cost)


@pytest.fixture(scope="module")
def net():
    return load_network()


@pytest.fixture(scope="module")
def p5():
    return load_problem("5")


@pytest.fixture(scope="module")
def hs(p5, net):
    from src.quso import HourSim
    return HourSim(p5.plants, p5.demand[HOUR], net)


# ---------------------------------------------------------------- grid model
def test_grid_is_the_rts_three_area_equivalent(net):
    B = net.laplacian
    np.testing.assert_allclose(B.sum(axis=1), 0, atol=1e-12)               # Laplacian rows sum to 0
    assert net.ref == "C" and net.B_bar.shape == (2, 2)
    lam = np.linalg.eigvalsh(net.B_bar)
    assert lam.min() > 0                                                   # Lem. 15: B_bar invertible
    assert np.linalg.cond(net.B_bar) == pytest.approx(7.64, abs=0.01)
    # RTS tie lines AB1-AB3 in parallel: b = 1/0.161 + 1/0.075 + 1/0.074
    assert net.lines[0][2] == pytest.approx(1 / 0.161 + 1 / 0.075 + 1 / 0.074, rel=1e-4)


def test_plants_sit_in_their_rts_areas(p5, net):
    assert [net.areas[a] for a in plant_areas(p5.plants, net)] == ["A", "A", "A", "B", "A"]


def test_power_flow_conserves_power(p5, net):
    """Everything generated in A and B arrives in C: rho_AC + rho_BC = generation."""
    for k in range(32):
        on = index_to_choice(k, 5)
        p = injections_mw(p5.plants, p5.demand[HOUR], on, net)
        f, _ = hour_network(p5.plants, p5.demand[HOUR], on, net)
        names = net.line_names()
        into_c = f[names.index("A-C")] + f[names.index("B-C")]
        assert into_c == pytest.approx(p[0] + p[1], abs=1e-6)


def test_power_flow_hand_example(net):
    """100 MW in at A, out at C: theta = B_bar^-1 p, flows split by the network, A-B carries A's share to B."""
    theta = solve_angles(np.array([1.0, 0.0]), net)                         # 100 MW = 1 pu
    f = net.line_matrix @ theta * BASE_MVA
    ab, ac, bc = f
    assert ac + bc == pytest.approx(100.0)
    assert ab == pytest.approx(bc)                                          # all of B's inflow leaves to C
    assert 0 < ab < ac                                                      # the direct line carries more


def test_transmission_cost_is_zero_when_lines_are_free(p5):
    free = load_network(cost_per_mwh=0.0)
    assert hour_network(p5.plants, p5.demand[HOUR], [1, 1, 0, 0, 0], free)[1] == 0.0


# ---------------------------------------------------------------- HHL
@pytest.mark.parametrize("b", [[3.5, 0.0], [3.0, 0.5], [0.5, 0.5], [0.0, 0.5]])
def test_hhl_solves_dc_power_flow(net, b):
    from src.hhl import hhl_solve
    x, p_success, fidelity = hhl_solve(net.B_bar, np.array(b), n_clock=4)
    x_true = np.linalg.solve(net.B_bar, b)
    assert fidelity > 0.9999
    assert np.linalg.norm(x - x_true) / np.linalg.norm(x_true) < 0.03       # norm via Rem. 7 rescaling
    assert 0 < p_success <= 1


def test_hhl_flow_difference_is_accurate(p5, net):
    """rho_AB is a small difference of two angles; 4 clock qubits keep its error under 2%."""
    from src.hhl import hhl_solve
    for k in VALID:
        pb = p_bar_pu(injections_mw(p5.plants, p5.demand[HOUR], index_to_choice(k, 5), net), net)
        x, _, _ = hhl_solve(net.B_bar, pb, n_clock=4)
        xt = np.linalg.solve(net.B_bar, pb)
        assert (x[0] - x[1]) / (xt[0] - xt[1]) == pytest.approx(1.0, abs=0.02)


def test_gershgorin_bound_is_an_upper_bound(net):
    from src.hhl import gershgorin_max
    assert gershgorin_max(net.B_bar) >= np.linalg.eigvalsh(net.B_bar).max()


# ---------------------------------------------------------------- QSim pieces
def test_prep_angles_load_the_injections(hs):
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Statevector

    from src.quso import prep_angles
    for k in (3, 11, 12):
        amps = hs.prep_amplitudes(k)
        th_flag, th_sys = prep_angles(amps)
        qc = QuantumCircuit(2)                       # qubit 0 = sys, qubit 1 = flag -> index sys + 2 flag
        qc.ry(th_flag, 1)
        qc.x(1)
        qc.cry(th_sys[0], 1, 0)
        qc.x(1)
        qc.cry(th_sys[1], 1, 0)
        np.testing.assert_allclose(Statevector(qc).data.real, amps, atol=1e-12)


def test_good_probability_encodes_the_ab_flow(hs):
    """a(x) = C^2 rho_AB^2 / (2 N^2 b_AB^2): inverting it gives back the flow."""
    for k in VALID:
        assert hs.flow_from_a(hs.a_exact(k)) == pytest.approx(abs(hs.rho_ab(k)), rel=1e-9)


def test_gate_level_qae_matches_matrix_simulation_for_one_choice(hs):
    """The circuit we send to qBraid (fixed choice) gives the same readout distribution as the fast simulator."""
    from qiskit.quantum_info import Statevector

    from src.quso import QSimMatrices, qae_circuit
    m = 3
    qm = QSimMatrices(hs, m)
    for k in VALID:
        sv = Statevector(qae_circuit(hs, m, choice=k))
        dist = sv.probabilities(qargs=list(range(sv.num_qubits - m, sv.num_qubits)))
        np.testing.assert_allclose(dist, qm.y_distribution(k), atol=1e-8)


def test_coherent_qae_matches_per_choice_simulation(hs):
    """Inside QAOA the plant qubits are in superposition; on a basis state |x> the coherent QSim
    must act exactly like the per-choice one (this is what makes the fast simulation exact)."""
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Statevector

    from src.quso import QSimMatrices, qae_circuit
    m = 2
    qc = qae_circuit(hs, m)
    qm = QSimMatrices(hs, m)
    for k in VALID:
        prep = QuantumCircuit(qc.num_qubits)
        for i in range(hs.n):
            if (k >> i) & 1:
                prep.x(i)
        sv = Statevector(prep.compose(qc))
        dist = sv.probabilities(qargs=list(range(qc.num_qubits - m, qc.num_qubits)))
        np.testing.assert_allclose(dist, qm.y_distribution(k), atol=1e-8)


def test_qae_reads_the_ab_flow_with_10_bits(hs):
    """With m = 10 (1,023 Grover calls) the most likely readout is within 3% of the exact flow."""
    from src.quso import QSimMatrices, qae_estimate
    qm = QSimMatrices(hs, 10)
    for k in VALID:
        est = hs.flow_from_a(qae_estimate(qm.y_distribution(k), 10))
        assert est == pytest.approx(abs(hs.rho_ab(k)), rel=0.03)


def test_qae_is_too_coarse_with_few_bits(hs):
    """With m = 4 the readout cannot tell the flow from zero: this is the O(1/eps) price of the readout."""
    from src.quso import QSimMatrices, qae_estimate
    qm = QSimMatrices(hs, 4)
    assert all(qae_estimate(qm.y_distribution(k), 4) == 0.0 for k in VALID)


def test_qae_error_within_brassard_bound(hs):
    """The readout error is within the textbook bound (around the amplitude HHL actually produces)."""
    from src.quso import QSimMatrices, a_from_y, qae_error_bound
    m = 8
    qm = QSimMatrices(hs, m)
    for k in VALID:
        dist = qm.y_distribution(k)
        a_est = float(a_from_y(int(np.argmax(dist)), m))
        assert abs(a_est - hs.a_exact(k)) <= qae_error_bound(hs.a_exact(k), m) + 0.0005   # + HHL bias


def test_cost_layer_applies_the_transmission_phase(hs):
    """QSim^dagger P(gamma) QSim |x>|0> = e^{-i gamma c|rho_AB|} |x>|0> (paper Thm. 10), up to readout error."""
    from src.quso import QSimMatrices
    m = 10
    qm = QSimMatrices(hs, m)
    ysin = np.sin(np.pi * np.arange(2 ** m) / 2 ** m)
    gamma = 1e-3                                       # phase = gamma * cost ($) -> about 0.6 rad at 600 $
    for k in VALID:
        v = qm.cost_layer(k, gamma * hs.K * ysin)
        overlap = v[0]                                 # amplitude back on |0> (y = 0, work = 0)
        assert abs(overlap) > 0.95                     # returns (mostly) to |0>: little garbage left
        expected = -gamma * hs.c_ab * abs(hs.rho_ab(k))
        assert np.angle(overlap) == pytest.approx(expected, abs=0.05)


def test_cost_layer_is_identity_at_zero_phase(hs):
    from src.quso import QSimMatrices
    qm = QSimMatrices(hs, 6)
    v = qm.cost_layer(3, np.zeros(2 ** 6))
    assert abs(v[0]) == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------- QuSO-QAOA
def test_quso_probabilities_are_a_distribution(p5, net):
    from src.quso import QuSOHour
    qh = QuSOHour(p5.plants, p5.demand[HOUR], p5.reserve[HOUR], [1, 1, 0, 0, 0], [], [], net, m=4)
    p = qh.probs(0.7, 0.4)
    assert p.sum() == pytest.approx(1.0, abs=1e-9) and p.min() > -1e-12
    np.testing.assert_allclose(qh.probs(0.0, 0.4), 1 / 256, atol=1e-12)   # no phase -> mixer keeps uniform


def test_quso_matches_plain_qaoa_when_qsim_is_off_or_phase_is_tiny(p5, net):
    """At $2/MWh the transmission phase is ~1e-4 of the QUBO's energy range, so QuSO ~ plain QAOA."""
    from src.quso import QuSOHour
    args = (p5.plants, p5.demand[HOUR], p5.reserve[HOUR], [1, 1, 0, 0, 0], [], [], net)
    a = QuSOHour(*args, m=6).probs(1.0, 0.5)
    b = QuSOHour(*args, m=6, qsim=False).probs(1.0, 0.5)
    assert np.abs(a - b).max() < 1e-4


def test_quso_day_gives_a_valid_schedule_for_a_few_hours(p5, net):
    from src.check import check_schedule
    from src.quso import quso_day
    short = replace(p5, demand=p5.demand[:3], reserve=p5.reserve[:3])
    schedule, log = quso_day(short, net, m=4, shots=50, maxiter=5)
    assert schedule.shape == (3, 5) and len(log) == 3
    assert check_schedule(short.plants, short.demand, short.reserve, schedule, verbose=False)["valid"]


# ---------------------------------------------------------------- condition number (paper Lem. 19 / 21)
def test_grounded_laplacian_condition_number_grows_with_grid_size():
    """For the reduced Laplacian of any grid, the all-ones vector gives lambda_min <= d_ref / (N - 1)
    (Rayleigh quotient), so kappa grows at least linearly in N, even on expander graphs. In particular
    lambda_min falls below the Fiedler value lambda_2, the opposite of the last inequality of Lem. 19,
    and kappa passes the constant bound of Lem. 21 (d = 3: 4 / (1/2 - sqrt(2)/3)^2, about 4,892)."""
    nx = pytest.importorskip("networkx")
    kappas = []
    for N in (64, 256, 1024):
        g = nx.random_regular_graph(3, N, seed=1)
        L = nx.laplacian_matrix(g).toarray().astype(float)
        lam2 = np.linalg.eigvalsh(L)[1]
        mu = np.linalg.eigvalsh(L[:-1, :-1])
        assert mu[0] <= 3 / (N - 1) + 1e-12                 # Rayleigh bound
        assert mu[0] < lam2                                  # lambda_min(B_bar) < lambda_2(L)
        kappas.append(mu[-1] / mu[0])
    assert kappas[2] / kappas[0] > 10                       # 16x more buses -> >10x larger kappa
    bound = 4 / (0.5 - np.sqrt(2) / 3) ** 2
    g = nx.random_regular_graph(3, 2048, seed=1)
    L = nx.laplacian_matrix(g).toarray().astype(float)
    mu = np.linalg.eigvalsh(L[:-1, :-1])
    assert mu[-1] / mu[0] > bound


# ---------------------------------------------------------------- network MILP
def test_network_milp_with_free_lines_is_the_organizers_milp(p5, milp):
    from src.network_milp import solve_network_milp
    r = solve_network_milp(p5.plants, p5.demand, p5.reserve, load_network(cost_per_mwh=0.0))
    assert r["cost"] == pytest.approx(milp["cost"], rel=1e-6)
    assert r["transmission_cost"] == pytest.approx(0.0, abs=1e-6)


def test_network_milp_is_a_lower_bound(p5, net, milp):
    """No schedule (with merit-order dispatch) can beat the network MILP's total cost."""
    from src.network_milp import solve_network_milp, total_cost
    r = solve_network_milp(p5.plants, p5.demand, p5.reserve, net)
    blind = total_cost(p5, milp["schedule"], net)
    assert r["cost"] <= blind["total"] + 1e-6
    assert r["cost"] >= milp["cost"] - 1e-6                                 # lines only add cost
    assert r["transmission_cost"] > 0

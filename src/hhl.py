"""HHL for the DC power flow B_bar theta = p_bar (the linear-system solver inside QSim).

Paper: arXiv:2305.08482 uses a QSVT linear solver (Thm. 5) and notes QPE-based HHL as the
textbook alternative. At our size (B_bar is 2 x 2, one system qubit) HHL is the clearer choice:

    1. load |b> = p_bar / |p_bar|                          (StatePreparation)
    2. QPE with U = exp(i B_bar t) writes each eigenvalue lambda into the clock register
       as k = lambda t 2^n_c / (2 pi)
    3. rotate an ancilla by RY(2 arcsin(C / lambda_k)), so |1> gets amplitude C / lambda
    4. undo the QPE
    5. keep the shots where the ancilla is 1: the system register then holds B_bar^-1 |b>,
       normalized; the norm comes from the success probability (paper Rem. 7):
            P(ancilla = 1) = C^2 |B_bar^-1 |b>|^2   ->   |theta| = |p_bar| sqrt(P) / C

Scaling t needs an upper bound on lambda_max. We use the Gershgorin bound of paper Cor. 6
(lambda_max <= 2 d_max), so no eigen-decomposition is needed. C is the smallest eigenvalue
the clock can represent, so every rotation angle is valid.
"""
import numpy as np
from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit.library import QFTGate, StatePreparation, UCRYGate, UnitaryGate
from qiskit.quantum_info import Statevector
from scipy.linalg import expm


def gershgorin_max(A):
    """Upper bound on the largest eigenvalue (paper Cor. 6): max_i (a_ii + sum_j |a_ij|)."""
    A = np.asarray(A)
    return float(np.max(np.abs(np.diag(A)) + np.abs(A).sum(axis=1) - np.abs(np.diag(A))))


def clock_scaling(A, n_clock, lam_max=None):
    """Evolution time t and constant C. lambda_max maps to clock value 2^n_c - 1 (no wrap-around)."""
    lam_max = gershgorin_max(A) if lam_max is None else lam_max
    t = 2 * np.pi * (2 ** n_clock - 1) / (2 ** n_clock * lam_max)
    C = 2 * np.pi / (t * 2 ** n_clock)          # eigenvalue of clock value 1
    return t, C


def inversion_angles(n_clock, t, C):
    """RY angle for each clock value k: 2 arcsin(C / lambda_k), lambda_k = 2 pi k / (t 2^n_c); k=0 -> 0."""
    angles = [0.0]
    for k in range(1, 2 ** n_clock):
        lam = 2 * np.pi * k / (t * 2 ** n_clock)
        angles.append(2 * np.arcsin(min(1.0, C / lam)))
    return angles


def qpe(A, n_clock, t, sys, clock):
    """QPE of U = exp(i A t) on the system register. Returns the circuit (no measurement)."""
    qc = QuantumCircuit(clock, sys)
    qc.h(clock)
    for j in range(n_clock):
        U = UnitaryGate(expm(1j * A * t * 2 ** j), label=f"U^{2 ** j}")
        qc.append(U.control(1), [clock[j], *sys])
    qc.append(QFTGate(n_clock).inverse(), clock)
    return qc


def hhl_core(A, n_clock, lam_max=None):
    """HHL without state preparation: acts on (clock, sys, anc). Returns (circuit, t, C)."""
    A = np.asarray(A, dtype=float)
    n_sys = int(np.log2(len(A)))
    t, C = clock_scaling(A, n_clock, lam_max)
    clock, sys, anc = QuantumRegister(n_clock, "clock"), QuantumRegister(n_sys, "sys"), QuantumRegister(1, "anc")
    qc = QuantumCircuit(clock, sys, anc)
    phase_est = qpe(A, n_clock, t, sys, clock)
    qc.compose(phase_est, [*clock, *sys], inplace=True)
    # UCRYGate: the k-th angle is applied when the control register holds k (qubit 0 = least significant).
    qc.append(UCRYGate(inversion_angles(n_clock, t, C)), [anc[0], *clock])
    qc.compose(phase_est.inverse(), [*clock, *sys], inplace=True)
    return qc, t, C


def hhl_circuit(A, b, n_clock=4, lam_max=None):
    """Full HHL for A x = b: state preparation + core. Qubit order: clock, sys, anc."""
    core, t, C = hhl_core(A, n_clock, lam_max)
    b = np.asarray(b, dtype=float)
    qc = QuantumCircuit(*core.qregs)
    qc.append(StatePreparation(b / np.linalg.norm(b)), qc.qregs[1])
    qc.compose(core, inplace=True)
    return qc, t, C


def hhl_solve(A, b, n_clock=4, lam_max=None):
    """Run HHL on the exact statevector. Returns (x_estimate, success_probability, fidelity).

    x_estimate is rescaled to the true size with paper Rem. 7. fidelity = |<x_hat|x_true_hat>|^2.
    """
    qc, t, C = hhl_circuit(A, b, n_clock, lam_max)
    n_clock_q, n_sys = qc.qregs[0].size, qc.qregs[1].size
    psi = Statevector(qc).data.reshape(2, 2 ** n_sys, 2 ** n_clock_q)   # [anc, sys, clock]
    good = psi[1, :, 0]                                                    # anc = 1, clock back to 0
    p_success = float(np.vdot(good, good).real)
    x_dir = good / np.sqrt(p_success)
    x_est = (x_dir * np.linalg.norm(b) * np.sqrt(p_success) / C).real
    x_true = np.linalg.solve(A, b)
    fidelity = abs(np.vdot(x_dir, x_true / np.linalg.norm(x_true))) ** 2
    return x_est, p_success, float(fidelity)

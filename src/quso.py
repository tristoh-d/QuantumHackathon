"""QPE-based quantum approach: QuSO (quantum simulation-based optimization) for one hour of UC.

Paper: Stein et al., arXiv:2305.08482. Thm. 10 builds the QAOA cost unitary for a cost that comes
out of a simulation:

    U_C(gamma) |x>|0> = QSim^dagger  P(gamma)  QSim |x>|0>  =  e^{-i gamma u(s(x))} |x>|0>

    QSim |x>|0> = |x>|u(s(x))>      simulation result written into an m-qubit register
    P(gamma)                        phase layer on that register (Lem. 8)

Our QSim, for the 3-area grid of src/network.py (plants in areas A and B, load in area C):

    1. load the injections of on/off choice x, controlled on the plant qubits:
           |x> |0>  ->  |x> ( |flag=0> (p_A, p_B) / N  +  |flag=1> sqrt(1 - |p_bar_x|^2 / N^2) |0> )
       N = max_x |p_bar_x| is one fixed constant for the hour, so the norm of p_bar_x is kept
       (the paper's Rem. 7 rescaling, done here with a flag qubit). Uniformly controlled RY gates.
    2. HHL (src/hhl.py) applies C B_bar^-1, flagged by anc = 1.
    3. H on the system qubit: its |1> amplitude is C (theta_A - theta_B) / (sqrt(2) N).
       The flow on line A-B is rho_AB = b_AB (theta_A - theta_B), so with "good" = (anc=1, flag=0, sys=1, clock=0)
           a(x) = P(good) = C^2 rho_AB^2 / (2 N^2 b_AB^2)            (per unit)
    4. Amplitude estimation (QPE on the Grover operator Q = A S_0 A^dagger S_good, paper Thm. 9)
       writes y with sin^2(pi y / 2^m) ~ a(x) into the m-qubit register, coherently.

The phase layer applies  gamma * K * sin(pi y / 2^m)  with K = c_AB * base * sqrt(2) N b_AB / C, so
the phase is gamma * c_AB |rho_AB| (the sin picks up the absolute value, as in the paper's Fig. 9).
The phase function is the same for every x: no cost table is loaded.

Why only line A-B: flows into the reference area C are never negative here (B_bar^-1 is entrywise
positive and every non-reference injection is generation), and rho_AC + rho_BC = total generation,
which equals demand for every valid choice. So c (rho_AC + rho_BC) is the same for every valid choice
of the hour (a global phase), and the only part of <c, |rho_x|> that needs the linear solve is
c_AB |rho_AB|.

The generation cost (the existing QUBO, src/qubo.py) is a separate, commuting cost unitary (paper
Rem. 13), applied with the same gamma.
"""
import numpy as np
from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit.library import QFTGate, UCRYGate
from qiskit.quantum_info import Operator

from src.hhl import hhl_core
from src.network import BASE_MVA, Network, injections_mw, p_bar_pu
from src.qubo import index_to_choice

# Register layout of the A operator (Qiskit little-endian index = position in this list).
A_LAYOUT = ("flag", "sys", "clock", "anc")
N_CLOCK = 4


# ---------------------------------------------------------------- the hour's data
class HourSim:
    """Everything QSim needs for one hour: injections of all 2^n choices, N, C, the A-B line."""

    def __init__(self, plants, demand_mw, net: Network, n_clock=N_CLOCK):
        if net.n_bus != 3:
            raise ValueError("QSim is written for the 3-area grid (B_bar is 2 x 2, one system qubit)")
        self.plants, self.demand, self.net, self.n_clock = plants, demand_mw, net, n_clock
        self.n = len(plants)
        self.p_bars = np.array([p_bar_pu(injections_mw(plants, demand_mw, index_to_choice(k, self.n), net), net)
                                for k in range(2 ** self.n)])
        self.N = max(float(np.linalg.norm(self.p_bars, axis=1).max()), 1e-9)
        self.core, self.t, self.C = hhl_core(net.B_bar, n_clock)
        self.ab = next(e for e, (i, j, *_) in enumerate(net.lines) if {net.areas[i], net.areas[j]} == {"A", "B"})
        _, _, self.b_ab, _, self.c_ab = net.lines[self.ab]

    # exact values (classical), for tests and scoring
    def rho_ab(self, k):
        """Exact flow on line A-B (MW) for choice k."""
        theta = np.linalg.solve(self.net.B_bar, self.p_bars[k])
        return self.b_ab * (theta[0] - theta[1]) * BASE_MVA

    def a_exact(self, k):
        """Ideal good-state probability a(x) (exact HHL)."""
        return (self.C * self.rho_ab(k) / BASE_MVA) ** 2 / (2 * self.N ** 2 * self.b_ab ** 2)

    def flow_from_a(self, a):
        """|rho_AB| in MW from an estimated a."""
        return np.sqrt(2) * self.N * self.b_ab * np.sqrt(np.maximum(a, 0)) / self.C * BASE_MVA

    @property
    def K(self):
        """Phase scale: cost in $ = K * sin(pi y / 2^m)."""
        return self.c_ab * self.flow_from_a(1.0)

    def prep_amplitudes(self, k):
        """Amplitudes over (sys, flag): index sys + 2 flag -> [p_A/N, p_B/N, junk, 0]."""
        pa, pb = self.p_bars[k] / self.N
        junk = np.sqrt(max(0.0, 1 - pa ** 2 - pb ** 2))
        return np.array([pa, pb, junk, 0.0])


# ---------------------------------------------------------------- circuits (gate level)
def prep_angles(amps):
    """RY angles that load real, non-negative amplitudes [a00, a10, a01, a11] (index sys + 2 flag):
    one RY on flag, then RY on sys controlled by flag."""
    a = np.asarray(amps, dtype=float).reshape(2, 2)      # a[flag, sys]
    w = np.sqrt((a ** 2).sum(axis=1))                    # weight of each flag value
    th_flag = 2 * np.arctan2(w[1], w[0])
    th_sys = [2 * np.arctan2(a[f, 1], a[f, 0]) if w[f] > 0 else 0.0 for f in (0, 1)]
    return th_flag, th_sys


def a_operator(hs: HourSim, controlled=True):
    """The A operator of amplitude estimation. With controlled=True it acts on (x, flag, sys, clock, anc)
    and loads choice x coherently; with controlled=False it returns one circuit per choice (no x qubits)."""
    flag, sys = QuantumRegister(1, "flag"), QuantumRegister(1, "sys")
    clock, anc = QuantumRegister(hs.n_clock, "clock"), QuantumRegister(1, "anc")
    angles = [prep_angles(hs.prep_amplitudes(k)) for k in range(2 ** hs.n)]

    def tail(qc):
        qc.compose(hs.core, [*clock, *sys, *anc], inplace=True)
        qc.h(sys)

    if not controlled:
        out = []
        for th_flag, th_sys in angles:
            qc = QuantumCircuit(flag, sys, clock, anc)
            qc.ry(th_flag, flag)
            qc.x(flag)
            qc.cry(th_sys[0], flag, sys)
            qc.x(flag)
            qc.cry(th_sys[1], flag, sys)
            tail(qc)
            out.append(qc)
        return out

    x = QuantumRegister(hs.n, "x")
    qc = QuantumCircuit(x, flag, sys, clock, anc)
    qc.append(UCRYGate([th for th, _ in angles]), [flag[0], *x])                       # flag | x
    sys_angles = [angles[k][1][f] for f in (0, 1) for k in range(2 ** hs.n)]           # control index k + 2^n f
    qc.append(UCRYGate(sys_angles), [sys[0], *x, flag[0]])                             # sys | x, flag
    tail(qc)
    return qc


def good_reflection(n_clock):
    """S_good = -1 on (anc=1, flag=0, sys=1, clock=0), on registers (flag, sys, clock, anc).

    clock=0 is part of "good" because HHL only succeeds when the clock is uncomputed back to 0
    (the same post-selection as hhl_solve); leftover clock garbage would bias the flow upward.
    """
    qc = QuantumCircuit(3 + n_clock)
    flag, sys, clock, anc = 0, 1, list(range(2, 2 + n_clock)), 2 + n_clock
    zeros = [flag, *clock]
    qc.x(zeros)
    qc.h(anc)
    qc.mcx([flag, sys, *clock], anc)
    qc.h(anc)
    qc.x(zeros)
    return qc


def zero_reflection(n_qubits):
    """S_0 = I - 2|0><0|: flips the sign of |0...0>."""
    qc = QuantumCircuit(n_qubits)
    qc.x(range(n_qubits))
    qc.h(n_qubits - 1)
    qc.mcx(list(range(n_qubits - 1)), n_qubits - 1)
    qc.h(n_qubits - 1)
    qc.x(range(n_qubits))
    return qc


def grover_operator(A, n_x, n_clock):
    """Q = A S_0 A^dagger S_good (sign convention of Brassard et al.), acting on the non-x registers;
    the x qubits (first n_x) are only controls of A."""
    work = list(range(n_x, A.num_qubits))
    qc = QuantumCircuit(A.num_qubits)
    qc.compose(good_reflection(n_clock), work, inplace=True)
    qc.compose(A.inverse(), inplace=True)
    qc.compose(zero_reflection(len(work)), work, inplace=True)
    qc.compose(A, inplace=True)
    qc.global_phase += np.pi           # the leading minus sign of Q
    return qc


def controlled_grover(A, n_x, n_clock):
    """Controlled Q with only the reflections controlled: c-Q = (phase -1 on ctrl) A c-S_0 A^dagger c-S_good.
    When ctrl = 0 the A and A^dagger cancel, so this equals Q.control(1) at a fraction of the gates.
    Qubit 0 is the control; then the qubits of A."""
    nA = A.num_qubits
    work = [1 + q for q in range(n_x, nA)]
    ctrl = 0
    flag, sys, clock, anc = work[0], work[1], work[2:2 + n_clock], work[2 + n_clock]
    qc = QuantumCircuit(nA + 1)
    # controlled S_good: -1 on (anc=1, flag=0, sys=1, clock=0)
    qc.x([flag, *clock])
    qc.h(anc)
    qc.mcx([ctrl, flag, sys, *clock], anc)
    qc.h(anc)
    qc.x([flag, *clock])
    qc.compose(A.inverse(), range(1, nA + 1), inplace=True)
    # controlled S_0: -1 on |0...0> of the work registers
    qc.x(work)
    qc.h(work[-1])
    qc.mcx([ctrl, *work[:-1]], work[-1])
    qc.h(work[-1])
    qc.x(work)
    qc.compose(A, range(1, nA + 1), inplace=True)
    qc.p(np.pi, ctrl)                  # the leading minus sign of Q, only when ctrl = 1
    return qc


def qae_circuit(hs: HourSim, m, choice=None, measure=False):
    """QSim as a gate-level circuit: |x>|0> -> |x> sum_y c_y(x) |garbage_y>|y>.

    choice=None: coherent in x (registers x, flag, sys, clock, anc, y), as used inside QAOA.
    choice=k:    one fixed on/off choice, no x register (registers flag, sys, clock, anc, y): the small
                 version we send to qBraid to check the readout of one choice.
    Controlled Q^(2^j) is built by repeating controlled-Q 2^j times, so gate counts are honest.
    Controlled-Q controls only the two reflections (controlled_grover).
    """
    if choice is None:
        A, n_x = a_operator(hs, controlled=True), hs.n
    else:
        A, n_x = a_operator(hs, controlled=False)[choice], 0
    cQ = controlled_grover(A, n_x, hs.n_clock).to_gate(label="c-Q")
    y = QuantumRegister(m, "y")
    qc = QuantumCircuit(*A.qregs, y)
    qc.compose(A, range(A.num_qubits), inplace=True)
    qc.h(y)
    for j in range(m):
        for _ in range(2 ** j):
            qc.append(cQ, [y[j], *range(A.num_qubits)])
    qc.append(QFTGate(m).inverse(), y)
    if measure:
        qc.measure_all()
    return qc


def resources(hs: HourSim, m, coherent=True):
    """Qubits and CX count of QSim (transpiled to rz/sx/x/cx), without building all 2^m - 1 copies:
    CX(QSim) = CX(A) + (2^m - 1) CX(controlled Q) + CX(QFT^-1)."""
    from qiskit import transpile

    def cx(qc):
        return transpile(qc, basis_gates=["rz", "sx", "x", "cx"], optimization_level=1).count_ops().get("cx", 0)

    A = a_operator(hs, controlled=True) if coherent else a_operator(hs, controlled=False)[0]
    n_x = hs.n if coherent else 0
    cQ = controlled_grover(A, n_x, hs.n_clock)
    iqft = QuantumCircuit(m)
    iqft.append(QFTGate(m).inverse(), range(m))
    cx_A, cx_cQ, cx_qft = cx(A), cx(cQ), cx(iqft)
    return dict(qubits=A.num_qubits + m, cx_A=cx_A, cx_controlled_Q=cx_cQ, grover_calls=2 ** m - 1,
                cx_total=cx_A + (2 ** m - 1) * cx_cQ + cx_qft,
                hhl_calls=1 + 2 * (2 ** m - 1))         # A once, then A and A^dagger in every Q


# ---------------------------------------------------------------- exact simulation (matrices)
class QSimMatrices:
    """Per-choice matrices of QSim, for fast exact simulation of the coherent circuit.

    The x qubits only act as controls, so for basis state |x> the circuit acts on the other registers
    as a fixed unitary that depends on x. Simulating each branch on its own is exact for the full
    coherent circuit (tests/test_quso.py checks this against qae_circuit).
    """

    def __init__(self, hs: HourSim, m):
        from scipy.linalg import schur
        self.hs, self.m, self.M = hs, m, 2 ** m
        self.dim = 2 ** (3 + hs.n_clock)
        Sg = Operator(good_reflection(hs.n_clock)).data
        S0 = np.eye(self.dim)
        S0[0, 0] = -1.0                                   # I - 2|0><0|
        s = np.arange(self.M)[:, None]
        self.A, self.Z, self.alpha, self.omega, self.back = [], [], [], [], []
        for A in a_operator(hs, controlled=False):
            Am = Operator(A).data
            Q = -(Am @ S0 @ Am.conj().T @ Sg)             # matches grover_operator (global phase pi)
            T, Z = schur(Q, output="complex")             # Q unitary -> T diagonal, Z unitary
            self.A.append(Am)
            self.Z.append(Z)
            self.alpha.append(Z.conj().T @ Am[:, 0])      # A|0> in Q's eigenbasis
            self.omega.append(np.angle(np.diag(T)))       # Q = Z diag(e^{i omega}) Z^dagger
            self.back.append((Am.conj().T @ Z).T)         # row vector in eigen coords -> A^dagger (standard basis)
        self.phase_s = [np.exp(1j * s * w[None, :]) for w in self.omega]   # e^{i s omega_e}, s = 0..M-1

    def qsim_eigen(self, k):
        """QSim |x=k>|0> in Q's eigenbasis: amp[y, e] = alpha_e (1/M) sum_s e^{i s omega_e} e^{-2 pi i s y / M}.
        (H on y gives 1/sqrt(M); controlled Q^s gives e^{i s omega}; the inverse QFT gives the other 1/sqrt(M).)"""
        return np.fft.fft(self.phase_s[k], axis=0) / self.M * self.alpha[k][None, :]

    def qsim(self, k):
        """QSim |x=k>|0>: state array [y, work] (2^m x dim), standard basis."""
        return self.qsim_eigen(k) @ self.Z[k].T

    def cost_layer_rows(self, k, phases):
        """QSim^dagger diag(e^{-i phases[y]}) QSim |x=k>|0>, as rows [s, work] BEFORE the final H on y.

        H on y is the same unitary for every choice, so inner products between choices do not need it.
        """
        amp = self.qsim_eigen(k) * np.exp(-1j * np.asarray(phases))[:, None]
        u = np.fft.ifft(amp, axis=0) * np.sqrt(self.M)                 # QFT on y
        u = u * self.phase_s[k].conj()                                  # controlled (Q^dagger)^s
        return u @ self.back[k]                                         # Z, then A^dagger

    def cost_layer(self, k, phases):
        """Full QSim^dagger P QSim |x=k>|0>, flattened (y major), including the final H on y."""
        rows = self.cost_layer_rows(k, phases)
        Hm = np.array([[1.0]])
        for _ in range(self.m):
            Hm = np.kron(Hm, np.array([[1, 1], [1, -1]]) / np.sqrt(2))
        return (Hm @ rows).ravel()

    def y_distribution(self, k):
        """Probability of each y (QAE readout) for choice k."""
        return (np.abs(self.qsim_eigen(k)) ** 2).sum(axis=1)


def iqft_rows(psi):
    """Inverse QFT on the y index (rows): |y> -> 1/sqrt(M) sum_z e^{-2 pi i y z / M} |z>."""
    M = psi.shape[0]
    return np.fft.fft(psi, axis=0) / np.sqrt(M)


def qft_rows(psi):
    M = psi.shape[0]
    return np.fft.ifft(psi, axis=0) * np.sqrt(M)


def a_from_y(y, m):
    """QAE estimate of a from register value y."""
    return np.sin(np.pi * np.asarray(y) / 2 ** m) ** 2


def qae_estimate(dist, m):
    """Most likely y -> estimate of a (what you would read from shots)."""
    return float(a_from_y(int(np.argmax(dist)), m))


def qae_error_bound(a, m):
    """Brassard et al. (2002) Thm. 12: |a_est - a| <= 2 pi sqrt(a(1-a)) / M + pi^2 / M^2, w.p. >= 8/pi^2."""
    M = 2 ** m
    return 2 * np.pi * np.sqrt(a * (1 - a)) / M + np.pi ** 2 / M ** 2


# ---------------------------------------------------------------- QuSO-QAOA (paper Thm. 10), one hour
def mixer(n_qubits, beta):
    """RX(2 beta) on every qubit, as a 2^n x 2^n matrix (bit j of the index = qubit j)."""
    rx = np.array([[np.cos(beta), -1j * np.sin(beta)], [-1j * np.sin(beta), np.cos(beta)]])
    M = np.array([[1.0 + 0j]])
    for _ in range(n_qubits):
        M = np.kron(rx, M)
    return M


class QuSOHour:
    """p=1 QAOA whose cost layer is  e^{-i gamma E_gen(z)}  x  QSim^dagger P(gamma) QSim  (paper Thm. 10).

    E_gen: the existing QUBO (src/qubo.py) with the hour's min up/down locks, over all 2^(n+n_slack) bitstrings.
    The transmission term is applied by QSim with the same gamma; both are divided by one energy scale S.
    Simulated exactly: the plant qubits are only controls of QSim, so each choice k carries its own
    ancilla state psi_k(gamma), and P(z) = sum_{x,x'} conj(W_zx) W_zx' <psi_k(x)|psi_k(x')>.
    """

    def __init__(self, plants, demand_mw, reserve_mw, was_on, must_on, must_off, net, m, n_slack=None,
                 qsim=True):
        from src.config import N_SLACK
        from src.qubo import add_locks, all_energies, build_qubo, plant_hour_costs, plant_index
        n_slack = N_SLACK if n_slack is None else n_slack
        Q, offset = build_qubo(plants, demand_mw, reserve_mw, was_on, n_slack=n_slack)
        Q, offset = add_locks(Q, offset, must_on, must_off, weight=2 * plant_hour_costs(plants, was_on).max())
        self.n, self.n_qubits, self.m, self.qsim_on = len(plants), len(plants) + n_slack, m, qsim
        self.E = all_energies(Q, offset)
        self.S = float(self.E.max() - self.E.min())
        self.kidx = plant_index(self.n, self.n_qubits)
        self.hs = HourSim(plants, demand_mw, net)
        self.trans = np.array([self.hs.c_ab * abs(self.hs.rho_ab(k)) for k in range(2 ** self.n)])
        if qsim:
            self.qm = QSimMatrices(self.hs, m)
            self.ysin = np.sin(np.pi * np.arange(2 ** m) / 2 ** m)
        self._gram_cache = {}

    def gram(self, gamma):
        """<psi_k|psi_k'> for all choices k, k' after the QSim cost layer (32 x 32)."""
        if not self.qsim_on:
            return np.ones((2 ** self.n, 2 ** self.n))
        key = round(float(gamma), 12)
        if key not in self._gram_cache:
            phases = gamma * self.hs.K * self.ysin / self.S
            P = np.array([self.qm.cost_layer_rows(k, phases).ravel() for k in range(2 ** self.n)])
            self._gram_cache = {key: P.conj() @ P.T}       # keep only the latest gamma
        return self._gram_cache[key]

    def probs(self, gamma, beta):
        c = np.exp(-1j * gamma * (self.E - self.E.min()) / self.S) / np.sqrt(len(self.E))
        W = mixer(self.n_qubits, beta) * c[None, :]
        G = self.gram(gamma)[np.ix_(self.kidx, self.kidx)]
        return np.einsum("zx,xy,zy->z", W.conj(), G, W).real

    def objective(self, probs):
        """Expected (generation QUBO + exact transmission cost), on the same 0..1 scale as run_qaoa."""
        return probs @ ((self.E - self.E.min()) + self.trans[self.kidx]) / self.S

    def tune(self, start=None, maxiter=40):
        from scipy.optimize import minimize
        f = lambda a: self.objective(self.probs(*a))
        if start is None:
            grid = [(g, b) for g in np.linspace(0.1, 3.0, 10) for b in np.linspace(0.1, 1.5, 6)]
            start = min(grid, key=f)
        res = minimize(f, start, method="COBYLA", options={"maxiter": maxiter, "rhobeg": 0.2})
        return res.x, self.probs(*res.x), res.nfev


def quso_day(problem, net, m=10, shots=200, seed=7, qsim=True, maxiter=40):
    """Hour-by-hour loop like src/scheduler.schedule_day, with the QuSO cost layer and a network-aware pick:
    among sampled valid choices keep the one with the lowest generation + transmission cost.
    qsim=False drops the QSim layer (plain QAOA, same tuner): the control for "does the network term help".
    Returns (schedule, log)."""
    from src.check import hour_cost, hour_ok, locks
    from src.network import hour_network
    from src.qubo import index_bits

    plants, demand, reserve, n = problem.plants, problem.demand, problem.reserve, problem.n
    rng = np.random.default_rng(seed)
    history, log, angles = [], [], None
    was_on = problem.start_state
    for t in problem.hours:
        must_on, must_off = locks(plants, history)
        qh = QuSOHour(plants, demand[t], reserve[t], was_on, must_on, must_off, net, m, qsim=qsim)
        angles, probs, nfev = qh.tune(start=angles, maxiter=maxiter)
        samples = rng.choice(len(probs), size=shots, p=np.clip(probs, 0, None) / np.clip(probs, 0, None).sum())
        bits = index_bits(qh.n_qubits)
        seen = [list(bits[k][:n]) for k in np.unique(qh.kidx[samples])]
        ok = [c for c in seen if hour_ok(plants, demand[t], reserve[t], c, must_on, must_off)]
        if not ok:
            ok = [c for c in seen if hour_ok(plants, demand[t], reserve[t], c)]
        total = lambda c: hour_cost(plants, demand[t], c, was_on) + hour_network(plants, demand[t], c, net)[1]
        pick = min(ok, key=total) if ok else list(bits[np.bincount(qh.kidx[samples]).argmax()][:n])
        valid = np.array([hour_ok(plants, demand[t], reserve[t], bits[z][:n], must_on, must_off)
                          for z in range(len(probs))])
        log.append(dict(hour=int(t), pick=pick, valid_share=float(probs[valid].sum()), nfev=int(nfev),
                        angles=list(angles)))
        history.append(pick)
        was_on = pick
    return np.array(history), log

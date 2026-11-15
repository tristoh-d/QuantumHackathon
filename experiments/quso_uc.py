"""The QPE / HHL approach (arXiv:2305.08482) on the 5-plant fleet and the 3-area RTS-GMLC grid.

    python -m experiments.quso_uc components            # HHL + amplitude-estimation accuracy, gate counts (local)
    python -m experiments.quso_uc day [--m 10]           # full day: QuSO vs plain QAOA vs MILP vs network MILP
    python -m experiments.quso_uc scaling                # oracle calls / resources vs grid size (the efficiency study)
    python -m experiments.quso_uc qbraid                 # HHL, A-operator and QAE circuits on the IonQ simulator
                                                         #   (ideal and forte-1 noise; free)

Outputs go to results/quso_*.{json,csv}; docs/qpe_results.md explains them.
"""
import argparse
import csv
import json
import time

import numpy as np

from src.config import RESULTS_DIR, load_problem
from src.network import load_network

HOUR = 14
CHOICES = (3, 11)       # COAL+GAS_CC, COAL+GAS_CC+PEAKER_B (valid at hour 14, different A-B flow)


def save_json(name, obj):
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / name
    path.write_text(json.dumps(obj, indent=1, default=float))
    print(f"saved {path.relative_to(RESULTS_DIR.parent)}")


# ---------------------------------------------------------------- components
def cmd_components(args):
    from src.hhl import hhl_solve
    from src.network import injections_mw, p_bar_pu
    from src.network_milp import solve_network_milp
    from src.qubo import index_to_choice
    from src.quso import HourSim, QSimMatrices, qae_error_bound, qae_estimate, resources

    problem, net = load_problem("5"), load_network()
    out = dict(hhl=[], qae=[], resources=[], phase=[])

    # 1. HHL on every hour of the network MILP's schedule
    sched = solve_network_milp(problem.plants, problem.demand, problem.reserve, net)["schedule"]
    for t in problem.hours:
        pb = p_bar_pu(injections_mw(problem.plants, problem.demand[t], sched[t], net), net)
        x, p_ok, fid = hhl_solve(net.B_bar, pb, n_clock=4)
        xt = np.linalg.solve(net.B_bar, pb)
        out["hhl"].append(dict(hour=int(t), fidelity=fid, rel_err_theta=float(np.linalg.norm(x - xt) / np.linalg.norm(xt)),
                               rel_err_flow_ab=float((x[0] - x[1]) / (xt[0] - xt[1]) - 1), p_success=p_ok))
    worst = max(out["hhl"], key=lambda r: abs(r["rel_err_flow_ab"]))
    print(f"HHL, 24 hours: min fidelity {min(r['fidelity'] for r in out['hhl']):.5f}, "
          f"worst A-B flow error {worst['rel_err_flow_ab']:+.2%} (hour {worst['hour']})")

    # 2. amplitude-estimation readout of |rho_AB| vs register size m
    hs = HourSim(problem.plants, problem.demand[HOUR], net)
    for m in (4, 6, 8, 10, 12):
        qm = QSimMatrices(hs, m)
        for k in CHOICES:
            dist = qm.y_distribution(k)
            a_est = qae_estimate(dist, m)
            out["qae"].append(dict(m=m, choice=k, flow_exact=abs(hs.rho_ab(k)), flow_est=float(hs.flow_from_a(a_est)),
                                   p_top=float(dist.max()), grover_calls=2 ** m - 1,
                                   bound_a=float(qae_error_bound(hs.a_exact(k), m)), a_exact=hs.a_exact(k), a_est=a_est))
        r = [q for q in out["qae"] if q["m"] == m]
        print(f"QAE m={m:>2} ({2 ** m - 1:>4} Grover calls): |rho_AB| "
              + ", ".join(f"{q['flow_exact']:.0f} -> {q['flow_est']:.0f} MW" for q in r))

    # 3. gate counts
    for m in (2, 3, 6, 10):
        for coherent in (False, True):
            r = resources(hs, m, coherent=coherent)
            out["resources"].append(dict(m=m, coherent=coherent, **r))
            print(f"resources m={m:>2} {'coherent in x' if coherent else 'one choice   '}: {r['qubits']} qubits, "
                  f"{r['cx_total']:,} CX, {r['hhl_calls']:,} HHL calls")

    # 4. the cost layer's phase
    gamma, m = 1e-3, 10
    qm = QSimMatrices(hs, m)
    ysin = np.sin(np.pi * np.arange(2 ** m) / 2 ** m)
    for k in CHOICES:
        v = qm.cost_layer(k, gamma * hs.K * ysin)
        out["phase"].append(dict(choice=k, gamma=gamma, phase=float(np.angle(v[0])),
                                 expected=float(-gamma * hs.c_ab * abs(hs.rho_ab(k))), return_amp=float(abs(v[0]))))
    print("cost layer phase (rad): " + ", ".join(f"{p['phase']:.4f} vs exact {p['expected']:.4f}" for p in out["phase"]))
    save_json("quso_components.json", out)


# ---------------------------------------------------------------- day
def cmd_day(args):
    from src.classical import run_milp
    from src.network_milp import solve_network_milp, total_cost
    from src.quso import quso_day
    from src.scheduler import schedule_day

    problem, net = load_problem("5"), load_network()
    rows = {}

    def record(name, schedule, seconds, **extra):
        r = total_cost(problem, schedule, net)
        rows[name] = dict(valid=r["valid"], generation=r["generation_cost"], transmission=r["transmission_cost"],
                          total=r["total"], overloads=len(r["overloads"]), seconds=seconds,
                          schedule=np.asarray(schedule).tolist(), **extra)
        print(f"{name:<34} valid={r['valid']!s:<5} total ${r['total']:>10,.0f}  "
              f"(gen ${r['generation_cost']:,.0f} + lines ${r['transmission_cost']:,.0f})  {seconds:7.2f} s")

    nm = solve_network_milp(problem.plants, problem.demand, problem.reserve, net)
    rows["network MILP (optimum)"] = dict(valid=True, generation=nm["generation_cost"], transmission=nm["transmission_cost"],
                                          total=nm["cost"], seconds=nm["seconds"], nodes=nm["nodes"],
                                          schedule=nm["schedule"].tolist())
    print(f"{'network MILP (optimum)':<34} total ${nm['cost']:>10,.0f}  {nm['seconds']:7.2f} s, {nm['nodes']} B&B node(s)")
    record("network MILP schedule, merit dispatch", nm["schedule"], nm["seconds"])
    m0 = run_milp(problem)
    record("MILP (network-blind)", m0["schedule"], m0["seconds"])

    t = time.perf_counter()
    s_qaoa, _ = schedule_day(problem, p=1, shots=args.shots, seed=args.seed)
    record("QAOA (existing, network-blind)", s_qaoa, time.perf_counter() - t)
    t = time.perf_counter()
    s_rand, _ = schedule_day(problem, sampler="random", shots=args.shots, seed=args.seed)
    record("random sampling", s_rand, time.perf_counter() - t)

    t = time.perf_counter()
    s_plain, log_plain = quso_day(problem, net, m=args.m, shots=args.shots, seed=args.seed, qsim=False)
    record("QAOA + network-aware pick", s_plain, time.perf_counter() - t,
           nfev=sum(r["nfev"] for r in log_plain))
    t = time.perf_counter()
    s_quso, log_quso = quso_day(problem, net, m=args.m, shots=args.shots, seed=args.seed, qsim=True)
    nfev = sum(r["nfev"] for r in log_quso)
    record(f"QuSO (HHL + QAE, m={args.m})", s_quso, time.perf_counter() - t, nfev=nfev,
           valid_share=float(np.mean([r["valid_share"] for r in log_quso])))
    hhl_per_circuit = 2 * (1 + 2 * (2 ** args.m - 1))          # QSim and QSim^dagger, p = 1
    rows["_counts"] = dict(m=args.m, shots=args.shots, hours=len(problem.hours),
                           hhl_calls_per_circuit=hhl_per_circuit,
                           hhl_calls_sampling=hhl_per_circuit * args.shots * len(problem.hours),
                           hhl_calls_tuning_on_device=hhl_per_circuit * args.shots * nfev,
                           classical_solves_brute_force=2 ** problem.n * len(problem.hours),
                           network_milp_nodes=nm["nodes"])
    save_json(f"quso_day_m{args.m}.json", rows)


# ---------------------------------------------------------------- scaling
def synthetic_grid(N, family, seed=0):
    """A Network with N buses: 'expander' (random 3-regular) or 'grid2d' (square lattice), RTS-like susceptances."""
    import networkx as nx

    from src.network import Network
    rng = np.random.default_rng(seed)
    if family == "expander":
        g = nx.random_regular_graph(3, N, seed=seed)
        while not nx.is_connected(g):
            seed += 1
            g = nx.random_regular_graph(3, N, seed=seed)
    else:
        side = int(round(np.sqrt(N)))
        g = nx.convert_node_labels_to_integers(nx.grid_2d_graph(side, side))
    lines = tuple((min(i, j), max(i, j), float(rng.uniform(5, 35)), 500.0, 2.0) for i, j in g.edges())
    n = g.number_of_nodes()
    return Network(areas=tuple(str(i) for i in range(n)), ref=str(n - 1), lines=lines)


def hhl_gates_model(N, kappa, s, eps=0.01):
    """Paper Rem. 8 gate count up to a constant: log2(N) sqrt(s_r s_c) kappa log(kappa sqrt(s_r s_c) / eps)."""
    return np.log2(max(N, 2)) * s * kappa * np.log(kappa * s / eps)


def cmd_scaling(args):
    from scipy.sparse import csc_matrix
    from scipy.sparse.linalg import splu

    from src.network_milp import solve_network_milp

    problem = load_problem("5")
    shots, m, M = 200, 10, problem.n
    # calibrate the HHL model's constant on our measured 3-bus circuit (68 CX, kappa 7.64, sparsity 2)
    net3 = load_network()
    k3 = float(np.linalg.cond(net3.B_bar))
    const = 68 / hhl_gates_model(net3.n_bus, k3, 2)
    rows = []
    sizes = [16, 36, 64, 144, 256, 576, 1024] if not args.quick else [16, 64, 256]
    for family in ("expander", "grid2d"):
        for N in sizes:
            net = synthetic_grid(N, family, seed=1)
            Bb = net.B_bar
            lam = np.linalg.eigvalsh(Bb)
            kappa = float(lam.max() / lam.min())
            s = int((np.abs(Bb) > 0).sum(axis=1).max())          # sparsity (non-zeros per row)
            # classical oracle: one DC power-flow solve (sparse LU), timed
            A = csc_matrix(Bb)
            b = np.random.default_rng(0).normal(size=len(Bb))
            t = time.perf_counter()
            for _ in range(20):
                splu(A).solve(b)
            t_solve = (time.perf_counter() - t) / 20
            # classical outer problem: network MILP for the day, plants on random buses, load spread evenly
            rng = np.random.default_rng(2)
            buses = list(rng.choice(net.keep, size=M, replace=False))
            share = np.full(net.n_bus, 1 / net.n_bus)
            r = solve_network_milp(problem.plants, problem.demand, problem.reserve, net, buses=buses, load_share=share)
            # quantum: HHL calls per hour = shots x (QSim + QSim^dagger) x (1 + 2 (2^m - 1)); gates per HHL call (model)
            hhl_calls_hour = shots * 2 * (1 + 2 * (2 ** m - 1))
            g_hhl = const * hhl_gates_model(N, kappa, s)
            rows.append(dict(family=family, N=net.n_bus, lines=len(net.lines), kappa=kappa, sparsity=s,
                             classical_solve_s=t_solve, brute_force_solves_per_hour=2 ** M,
                             milp_day_s=r["seconds"], milp_nodes=r["nodes"],
                             hhl_calls_per_hour=hhl_calls_hour, cx_per_hhl_model=g_hhl,
                             quantum_cx_per_day=hhl_calls_hour * g_hhl * 24))
            print(f"{family:<8} N={net.n_bus:>5} kappa={kappa:8.1f}  solve {t_solve * 1e3:7.3f} ms  "
                  f"MILP day {r['seconds']:6.2f} s ({r['nodes']} nodes)  quantum {hhl_calls_hour * g_hhl * 24:,.0f} CX/day")
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / "quso_scaling.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"saved {path.relative_to(RESULTS_DIR.parent)} (HHL model constant {const:.2f}, calibrated at 3 buses)")


# ---------------------------------------------------------------- qBraid
def cmd_qbraid(args):
    from qiskit import transpile
    from qiskit.quantum_info import Statevector

    from experiments.qbraid_driver import require_qbraid
    from src.config import DEVICES
    from src.hardware import log_run, submit_qbraid
    from src.hhl import hhl_circuit
    from src.quso import HourSim, a_operator, qae_circuit

    require_qbraid()
    problem, net = load_problem("5"), load_network()
    hs = HourSim(problem.plants, problem.demand[HOUR], net)
    device_id = DEVICES["ionq-sim"]
    out = []

    def circuits(k):
        pb = hs.p_bars[k]
        hhl, _, _ = hhl_circuit(net.B_bar, pb, n_clock=4)                 # clock 0-3, sys 4, anc 5
        A = a_operator(hs, controlled=False)[k]                           # flag 0, sys 1, clock 2-5, anc 6
        yield "hhl", hhl
        yield "A (Monte Carlo readout)", A
        for m in args.qae_m:
            yield f"QAE m={m}", qae_circuit(hs, m, choice=k)

    for k in CHOICES:
        for name, qc in circuits(k):
            exact = Statevector(qc).probabilities()
            tq = transpile(qc, basis_gates=["rz", "sx", "x", "cx"], optimization_level=1)
            cx = tq.count_ops().get("cx", 0)
            tq.measure_all()
            for noise in (None, "forte-1"):
                job = submit_qbraid(tq, device_id, shots=args.shots, noise_model=noise)
                note = f"quso | {name} | choice {k} | hour {HOUR}" + (f" | {noise} noise" if noise else " | ideal")
                log_run(device_id, job.id, args.shots, HOUR, 1, cx, status="submitted", note=note)
                counts = job.result().data.get_counts()
                log_run(device_id, job.id, args.shots, HOUR, 1, cx, status="completed", counts=counts, note=note)
                total = sum(counts.values())
                measured = np.zeros(len(exact))
                for key, c in counts.items():
                    measured[int(key.replace(" ", ""), 2)] += c / total
                row = dict(choice=k, circuit=name, noise=noise or "ideal", job_id=job.id, cx=cx, qubits=qc.num_qubits,
                           shots=args.shots, tvd=float(0.5 * np.abs(measured - exact).sum()),
                           **score(name, qc, measured, exact, hs, k))
                out.append(row)
                print(f"choice {k} {name:<24} {row['noise']:<8} {cx:>6} CX  TVD {row['tvd']:.3f}  "
                      f"|rho_AB| exact {abs(hs.rho_ab(k)):.0f} MW -> {row.get('flow_ab', float('nan')):.0f} MW")
    save_json("quso_qbraid.json", out)


def score(name, qc, measured, exact, hs, k):
    """Turn a measured distribution into the quantity that circuit estimates (|rho_AB| in MW)."""
    from src.quso import a_from_y
    idx = np.arange(len(measured))
    nc = hs.n_clock
    if name == "hhl":                       # clock 0..nc-1, sys nc, anc nc+1
        clock0 = (idx & (2 ** nc - 1)) == 0
        anc1 = ((idx >> (nc + 1)) & 1) == 1
        sys = (idx >> nc) & 1
        good = clock0 & anc1
        p_ok = measured[good].sum()
        if p_ok == 0:
            return dict(flow_ab=float("nan"), p_success=0.0)
        p1 = measured[good & (sys == 1)].sum() / p_ok
        # theta direction from the sys distribution (both components are positive here), norm from Rem. 7
        norm_theta = np.linalg.norm(hs.p_bars[k]) * np.sqrt(p_ok) / hs.C
        th = norm_theta * np.array([np.sqrt(1 - p1), np.sqrt(p1)])
        return dict(flow_ab=float(abs(hs.b_ab * (th[0] - th[1]) * 100)), p_success=float(p_ok))
    if name.startswith("A"):                # flag 0, sys 1, clock 2.., anc last
        good = (((idx >> 0) & 1) == 0) & (((idx >> 1) & 1) == 1) & (((idx >> 2) & (2 ** nc - 1)) == 0) \
            & (((idx >> (2 + nc)) & 1) == 1)
        a = measured[good].sum()
        return dict(flow_ab=float(hs.flow_from_a(a)), a=float(a), a_exact_circuit=float(exact[good].sum()))
    m = int(name.split("=")[1])             # QAE: y register = top m qubits
    y_dist = np.bincount(idx >> (qc.num_qubits - m), weights=measured, minlength=2 ** m)
    y = int(np.argmax(y_dist))
    return dict(flow_ab=float(hs.flow_from_a(a_from_y(y, m))), y=y, p_top=float(y_dist.max()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("components")
    d = sub.add_parser("day")
    d.add_argument("--m", type=int, default=10)
    d.add_argument("--shots", type=int, default=200)
    d.add_argument("--seed", type=int, default=7)
    s = sub.add_parser("scaling")
    s.add_argument("--quick", action="store_true")
    q = sub.add_parser("qbraid")
    q.add_argument("--shots", type=int, default=1000)
    q.add_argument("--qae-m", type=int, nargs="*", default=[2, 3])
    args = ap.parse_args()
    {"components": cmd_components, "day": cmd_day, "scaling": cmd_scaling, "qbraid": cmd_qbraid}[args.command](args)


if __name__ == "__main__":
    main()

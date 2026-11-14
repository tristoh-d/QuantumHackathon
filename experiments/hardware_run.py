"""Milestone 5: one hour's tuned QAOA circuit on a qBraid device, compared with the ideal simulator.

Run it in qBraid Lab (the qBraid-SDK kernel/environment has your credentials).

    python -m experiments.hardware_run --dry-run                         # build + Aer only, no qBraid
    python -m experiments.hardware_run                                   # IonQ free simulator, forte-1 noise
    python -m experiments.hardware_run --device quantinuum-emu           # free Quantinuum H2 emulator
    python -m experiments.hardware_run --device ionq-qpu --i-am-sure     # REAL hardware: uses credits

Order from the README: tune on Aer -> IonQ noisy simulator -> QPU (final circuit only, p=1, <= 200 shots).
Send the QPU job early: queues can take hours. Every job is logged to results/hardware_runs.csv.
"""
import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from experiments._common import todo_guard  # noqa: E402
from src.check import check_hour, hour_ok  # noqa: E402
from src.config import DEVICES, MAX_HARDWARE_SHOTS, QPU_DEVICES, RESULTS_DIR, load_problem  # noqa: E402
from src.hardware import (build_hardware_circuit, choice_shares, device_kind, log_run, run_aer,  # noqa: E402
                          submit_qbraid)
from src.plotting import plot_hardware_vs_sim  # noqa: E402
from src.qubo import choice_to_index, index_to_choice  # noqa: E402
from src.quantum import run_qaoa  # noqa: E402
from src.scheduler import schedule_day  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hour", type=int, default=14, help="hour to run (15 is the peak)")
    ap.add_argument("--device", default="ionq-sim", choices=sorted(DEVICES))
    ap.add_argument("--shots", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7, help="seed of the day-long QAOA run that builds the QUBO")
    ap.add_argument("--dry-run", action="store_true", help="only build the circuit and run Aer")
    ap.add_argument("--i-am-sure", action="store_true", help="required for QPU devices (uses credits)")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    device_id = DEVICES[args.device]
    if device_id in QPU_DEVICES and args.shots > MAX_HARDWARE_SHOTS:
        ap.error(f"hardware rule: at most {MAX_HARDWARE_SHOTS} shots")

    problem = load_problem("5")
    n, t = problem.n, args.hour
    with todo_guard("hardware_run"):
        # Reuse the QUBO the hour-by-hour loop built for this hour (locks included), then tune p=1.
        schedule, log = schedule_day(problem, p=1, shots=200, seed=args.seed)
    entry = log[t]
    angles, _ = run_qaoa(entry["Q"], entry["offset"], p=1, start=entry["angles"])
    qc, cx = build_hardware_circuit(entry["Q"], angles, p=1)
    print(f"Hour {t}: {qc.num_qubits} qubits, {cx} CX gates after transpiling (IonQ native ZZ count is lower)")

    sim_counts = run_aer(qc, shots=args.shots)
    sim_share = choice_shares(sim_counts, n)

    must_on, must_off = entry["must_on"], entry["must_off"]
    ref = check_hour(problem.plants, problem.demand[t], problem.reserve[t], schedule[t], was_on=entry["was_on"],
                     must_on=must_on, must_off=must_off, verbose=False)
    if ref["best_choice"] is None:
        raise SystemExit(f"No valid on/off choice at hour {t}; pick another --hour")
    best_k = choice_to_index(ref["best_choice"])
    is_valid = np.array([hour_ok(problem.plants, problem.demand[t], problem.reserve[t], index_to_choice(k, n),
                                 must_on, must_off) for k in range(2 ** n)])

    shares = [("Aer (ideal simulator)", sim_share)]
    hw_label = None
    if not args.dry_run:
        if device_id in QPU_DEVICES and not args.i_am_sure:
            raise SystemExit(f"{device_id} is real hardware and uses credits. Re-run with --i-am-sure "
                             "once this exact circuit is tuned on the noisy simulator.")
        noise = "forte-1" if args.device == "ionq-sim" else None
        job = submit_qbraid(qc, device_id, shots=args.shots, noise_model=noise, allow_qpu=args.i_am_sure)
        print(f"Device: {device_id} | Job ID: {job.id}   <- copy into docs/results.md")
        log_run(device_id, job.id, args.shots, t, 1, cx, status="submitted", note=args.note)
        counts = job.result().data.get_counts()
        log_run(device_id, job.id, args.shots, t, 1, cx, status="completed", counts=counts, note=args.note)
        hw_label = f"{device_id} ({device_kind(device_id)})" + (" + forte-1 noise" if noise else "")
        shares.append((hw_label, choice_shares(counts, n)))

    for name, share in shares:
        print(f"{name:<55} valid shots {share[is_valid].sum():5.0%}   best choice {share[best_k]:5.1%}")

    if hw_label:
        RESULTS_DIR.mkdir(exist_ok=True)
        ax = plot_hardware_vs_sim(sim_share, shares[-1][1], hw_label, problem.names, best_k, is_valid, t)
        out = RESULTS_DIR / f"hardware_hour{t}_{args.device}.png"
        ax.figure.savefig(out, dpi=150, bbox_inches="tight")
        plt.close(ax.figure)
        print(f"saved {out.relative_to(RESULTS_DIR.parent)}")


if __name__ == "__main__":
    main()

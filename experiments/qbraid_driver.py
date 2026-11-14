"""One driver for every qBraid run: pick a task, pick a device (local Aer, a simulator, or real hardware).

Run it in qBraid Lab (the qBraid-SDK kernel has your credentials), or locally after `pip install qbraid`
and `qbraid configure` (API key from account.qbraid.com).

    python -m experiments.qbraid_driver devices                                  # devices + live status/queue
    python -m experiments.qbraid_driver run --task uc --device aer               # local ideal sim, no qBraid
    python -m experiments.qbraid_driver run --task uc --device ionq-sim          # IonQ free sim, forte-1 noise
    python -m experiments.qbraid_driver run --task uc --device quantinuum-emu    # free H2 emulator
    python -m experiments.qbraid_driver run --task maxcut --device gpu-sv --shots 2048 --grid large
    python -m experiments.qbraid_driver run --task uc --device ionq-qpu --i-am-sure --no-wait   # REAL hardware
    python -m experiments.qbraid_driver fetch <JOB_ID>                           # collect a queued job later

Tasks:
    uc      one hour of the unit-commitment QUBO (milestone 5), tuned p=1, compared with the ideal simulator
    maxcut  the Max-Cut primer circuit, angles tuned on Aer, then sampled on the chosen device

Angles are always tuned locally (the optimizer runs the circuit dozens of times); only the final, tuned
circuit is sent to qBraid. QPU devices need --i-am-sure and at most 200 shots. Every qBraid job is logged
to results/hardware_runs.csv, so a job ID is never lost even if this script is interrupted.
"""
import argparse
import csv
import sys
import time
from datetime import datetime, timezone

import numpy as np

from src.config import DEVICES, MAX_HARDWARE_SHOTS, QPU_DEVICES, REPO_ROOT, RESULTS_DIR
from src.hardware import RUN_LOG, device_kind, log_run, submit_qbraid

LOCAL = "aer"
NOISE_MODELS = {"ionq-sim": "forte-1"}   # free IonQ simulator: emulate Forte's noise by default

# docs/results.md "Milestone 5: hardware run record" table. UC runs on qBraid get a row there automatically
# (results/ is git-ignored, so this is the copy that gets committed).
RESULTS_MD = REPO_ROOT / "docs" / "results.md"
RESULTS_MD_HEADER = "| Device | Kind (simulator / emulator / QPU) | Job ID |"
RESULTS_MD_COLUMNS = ["device", "kind", "job_id", "hour", "shots", "p", "cx", "status", "valid", "best", "queue"]


def record_in_results_md(add=True, **cells):
    """Add a row to the hardware table in docs/results.md, or update the row that already has this job ID.

    On update, only the non-empty cells passed in replace the old ones (so `fetch` can just set the status).
    With add=False, only an existing row is updated.
    """
    if not RESULTS_MD.exists():
        return
    lines = RESULTS_MD.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.startswith(RESULTS_MD_HEADER)), None)
    if start is None:
        print(f"(hardware table not found in {RESULTS_MD.name}; row not added)")
        return
    end = start + 2                                   # skip header + |---| line
    while end < len(lines) and lines[end].startswith("|"):
        end += 1

    def to_line(values):
        return "| " + " | ".join(str(v) for v in values) + " |\n"

    new = [cells.get(c, "") for c in RESULTS_MD_COLUMNS]
    for i in range(start + 2, end):
        old = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if len(old) == len(new) and old[2] == str(cells["job_id"]):
            lines[i] = to_line(n if str(n) != "" else o for n, o in zip(new, old))
            action = "updated"
            break
    else:
        if not add:
            return
        lines.insert(end, to_line(new))
        action = "added"
    RESULTS_MD.write_text("".join(lines), encoding="utf-8")
    print(f"{action} row for this job in docs/{RESULTS_MD.name}")


def require_qbraid():
    """Stop early with a clear message if qBraid can't be used from here (before minutes of tuning)."""
    import importlib.util
    import os
    from pathlib import Path

    if importlib.util.find_spec("qbraid") is None:
        sys.exit("qBraid SDK not installed in this Python. Run:  pip install -r requirements.txt\n"
                 "(or use --device aer for a local run).")
    has_config = (Path.home() / ".qbraid" / "qbraidrc").exists()
    if not (os.environ.get("QBRAID_API_KEY") or os.environ.get("QBRAID_ACCESS_TOKEN") or has_config):
        sys.exit("No qBraid API key found. Put it in .env as  QBRAID_API_KEY=...  (copy .env.example),\n"
                 "or run  qbraid configure.  Get the key at https://account.qbraid.com.")


def _queue_time(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


# ---------------------------------------------------------------- tasks: build circuit + score counts
def prepare_uc(args):
    """Tune one hour's QUBO circuit. Returns (circuit, meta, score) where score(counts) prints a summary."""
    from experiments._common import todo_guard
    from src.check import check_hour, hour_ok
    from src.config import load_problem
    from src.hardware import build_hardware_circuit, choice_shares
    from src.qubo import choice_to_index, index_to_choice
    from src.quantum import run_qaoa
    from src.scheduler import schedule_day

    problem = load_problem(args.fleet)
    n, t = problem.n, args.hour
    kwargs = {"n_slack": args.n_slack} if args.n_slack is not None else {}
    with todo_guard("qbraid_driver"):
        schedule, log = schedule_day(problem, p=1, shots=200, seed=args.seed, **kwargs)
    entry = log[t]
    angles, _ = run_qaoa(entry["Q"], entry["offset"], p=1, start=entry["angles"])
    qc, cx = build_hardware_circuit(entry["Q"], angles, p=1)

    ref = check_hour(problem.plants, problem.demand[t], problem.reserve[t], schedule[t], was_on=entry["was_on"],
                     must_on=entry["must_on"], must_off=entry["must_off"], verbose=False)
    if ref["best_choice"] is None:
        raise SystemExit(f"No valid on/off choice at hour {t}; pick another --hour")
    best_k = choice_to_index(ref["best_choice"])
    is_valid = np.array([hour_ok(problem.plants, problem.demand[t], problem.reserve[t], index_to_choice(k, n),
                                 entry["must_on"], entry["must_off"]) for k in range(2 ** n)])

    def score(label, counts):
        share = choice_shares(counts, n)
        valid, best = f"{share[is_valid].sum():.0%}", f"{share[best_k]:.1%}"
        print(f"{label:<55} valid shots {valid:>5}   best choice {best:>5}")
        return dict(share=share, valid=valid, best=best)

    def plot(sim_share, hw_share, hw_label):
        try:
            import matplotlib
        except ImportError:
            print("(chart skipped: matplotlib not installed; `pip install matplotlib` to get it. "
                  "Counts are already saved in results/.)")
            return
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        from src.plotting import plot_hardware_vs_sim
        ax = plot_hardware_vs_sim(sim_share, hw_share, hw_label, problem.names, best_k, is_valid, t)
        out = RESULTS_DIR / f"hardware_hour{t}_fleet{args.fleet}_{args.device}.png"
        ax.figure.savefig(out, dpi=150, bbox_inches="tight")
        plt.close(ax.figure)
        print(f"saved {out.relative_to(RESULTS_DIR.parent)}")

    meta = dict(hour=t, p=1, cx=cx, desc=f"UC fleet {args.fleet}, hour {t}")
    return qc, meta, score, plot


def prepare_maxcut(args):
    """Tune the Max-Cut primer on Aer. Returns (circuit, meta, score, plot)."""
    from experiments._common import todo_guard
    from qiskit import transpile

    from src import maxcut

    n, edges = (maxcut.N_SMALL, maxcut.EDGES_SMALL) if args.grid == "small" else (maxcut.N_LARGE, maxcut.EDGES_LARGE)
    with todo_guard("qbraid_driver"):
        result = maxcut.optimize(n, edges, p=args.p, seed=args.seed)
        qc = maxcut.qaoa_circuit(result.x, n, edges, args.p)
    cx = transpile(qc, basis_gates=["rz", "sx", "x", "cx"]).count_ops().get("cx", 0)
    best_possible = maxcut.brute_force(n, edges)[0]

    def score(label, counts):
        total = sum(counts.values())
        cuts = {bs: maxcut.cut_value(bs.replace(" ", "")[::-1], edges) for bs in counts}  # qubit 0 is last char
        avg = sum(cuts[bs] * c for bs, c in counts.items()) / total
        hit = sum(c for bs, c in counts.items() if cuts[bs] == best_possible) / total
        print(f"{label:<55} average cut {avg:5.2f} / {best_possible}   best cut in {hit:5.1%} of shots"
              f"   (random guessing: {maxcut.random_average_cut(edges):.1f})")
        return None

    meta = dict(hour="", p=args.p, cx=cx, desc=f"Max-Cut {args.grid} grid ({n} nodes), p={args.p}")
    return qc, meta, score, None


TASKS = {"uc": prepare_uc, "maxcut": prepare_maxcut}


# ---------------------------------------------------------------- commands
def cmd_devices(args):
    """Print every configured device with its qBraid status and queue depth."""
    print(f"{LOCAL:<16} {'local Aer (ideal, free, instant)':<42} -")
    try:
        from qbraid.runtime import QbraidProvider
        provider = QbraidProvider()
    except Exception as e:   # no qbraid installed or no credentials
        provider = None
        print(f"\n(qBraid unavailable: {e})")
    for name, device_id in DEVICES.items():
        status = queue = "?"
        if provider is not None:
            try:
                device = provider.get_device(device_id)
                status = getattr(device.status(), "name", str(device.status()))
                try:
                    queue = device.queue_depth()
                except Exception:
                    queue = "-"
            except Exception as e:
                status = f"error: {type(e).__name__}"
        print(f"{name:<16} {device_id:<42} {device_kind(device_id):<9} status={status:<12} queue={queue}")


def cmd_run(args):
    device_id = None if args.device == LOCAL else DEVICES[args.device]
    is_qpu = device_id in QPU_DEVICES
    if is_qpu and args.shots > MAX_HARDWARE_SHOTS:
        sys.exit(f"Hardware rule: at most {MAX_HARDWARE_SHOTS} shots on a QPU (got {args.shots}).")
    if is_qpu and not args.i_am_sure:
        sys.exit(f"{device_id} is real hardware and uses credits. Tune on aer / ionq-sim first, "
                 "then re-run with --i-am-sure.")

    if device_id is not None:
        require_qbraid()
    qc, meta, score, plot = TASKS[args.task](args)
    print(f"{meta['desc']}: {qc.num_qubits} qubits, {meta['cx']} CX gates after transpiling")

    from src.hardware import run_aer
    sim_counts = run_aer(qc, shots=args.shots, seed=args.seed)
    sim = score("Aer (ideal simulator)", sim_counts)
    if device_id is None:
        return

    noise = None if args.no_noise else NOISE_MODELS.get(args.device)
    job = submit_qbraid(qc, device_id, shots=args.shots, noise_model=noise, allow_qpu=args.i_am_sure)
    note = " | ".join(x for x in (args.task, meta["desc"], args.note) if x)
    log_run(device_id, job.id, args.shots, meta["hour"], meta["p"], meta["cx"], status="submitted", note=note)
    submitted_at = time.time()
    print(f"Device: {device_id} | Job ID: {job.id}")
    md_row = dict(device=device_id + (f" ({noise} noise)" if noise else ""), kind=device_kind(device_id),
                  job_id=job.id, hour=meta["hour"], shots=args.shots, p=meta["p"], cx=meta["cx"])
    in_table = args.task == "uc"     # the docs/results.md table is the UC hardware record

    if args.no_wait:
        if in_table:
            record_in_results_md(**md_row, status="submitted")
        print(f"Submitted without waiting. Collect it later with:\n"
              f"    python -m experiments.qbraid_driver fetch {job.id}")
        return

    counts = job.result().data.get_counts()
    queue = _queue_time(time.time() - submitted_at)
    log_run(device_id, job.id, args.shots, meta["hour"], meta["p"], meta["cx"], status="completed",
            counts=counts, note=note)
    label = f"{device_id} ({device_kind(device_id)})" + (f" + {noise} noise" if noise else "")
    hw = score(label, counts)
    if in_table:
        record_in_results_md(**md_row, status="completed", valid=hw["valid"], best=hw["best"], queue=queue)
    if plot is not None:
        plot(sim["share"], hw["share"], label)


def _submitted_row(job_id):
    """The 'submitted' row for job_id in results/hardware_runs.csv, or None."""
    if not RUN_LOG.exists():
        return None
    with open(RUN_LOG, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["job_id"] == job_id]
    return rows[0] if rows else None


def cmd_fetch(args):
    """Check on a submitted job; if it finished, save its counts and log it as completed."""
    require_qbraid()
    from qbraid.runtime import QbraidJob

    job = QbraidJob(args.job_id)
    status = job.status()
    print(f"Job {args.job_id}: {getattr(status, 'name', status)}")
    if not job.is_terminal_state():
        try:
            print(f"Queue position: {job.queue_position()}")
        except Exception:
            pass
        print("Not finished yet; try again later (or pass --wait to block until it is).")
        if not args.wait:
            return
    counts = job.result().data.get_counts()
    row = _submitted_row(args.job_id) or {}
    log_run(row.get("device", ""), args.job_id, row.get("shots", sum(counts.values())), row.get("hour", ""),
            row.get("p", ""), row.get("cx_gates", ""), status="completed", counts=counts, note=row.get("note", ""))
    top = dict(sorted(counts.items(), key=lambda kv: -kv[1])[:8])
    print(f"Counts saved and logged to {RUN_LOG.relative_to(RESULTS_DIR.parent)}. Most common: {top}")
    if row.get("utc"):    # upper bound: from submission to when we fetched it
        waited = datetime.now(timezone.utc) - datetime.fromisoformat(row["utc"])
        queue = "≤ " + _queue_time(waited.total_seconds())
    else:
        queue = ""
    # Marks the row completed if `run --no-wait` added one; valid/best shares need the task context, so
    # fill those in by hand from the saved counts (or re-run the task on the same device).
    record_in_results_md(add=row.get("note", "").startswith("uc"), job_id=args.job_id, device=row.get("device", ""), kind=device_kind(row.get("device", "")),
                         hour=row.get("hour", ""), shots=row.get("shots", ""), p=row.get("p", ""),
                         cx=row.get("cx_gates", ""), status="completed", queue=queue)
    print("Re-run the matching `run` command with --device aer to compare against the ideal simulator.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="list devices with live status and queue depth")

    run = sub.add_parser("run", help="tune locally, then run on the chosen device")
    run.add_argument("--task", choices=sorted(TASKS), default="uc")
    run.add_argument("--device", choices=[LOCAL] + sorted(DEVICES), default=LOCAL)
    run.add_argument("--shots", type=int, default=200)
    run.add_argument("--seed", type=int, default=7)
    run.add_argument("--no-wait", action="store_true", help="submit and exit (use `fetch` later); good for QPU queues")
    run.add_argument("--no-noise", action="store_true", help="run ionq-sim without the forte-1 noise model")
    run.add_argument("--i-am-sure", action="store_true", help="required for QPU devices (uses credits)")
    run.add_argument("--note", default="")
    uc = run.add_argument_group("uc task")
    uc.add_argument("--hour", type=int, default=14, help="hour to run (15 is the peak)")
    uc.add_argument("--fleet", choices=["5", "10"], default="5")
    uc.add_argument("--n-slack", type=int, default=None, help="slack bits (the 10-plant fleet may need more)")
    mc = run.add_argument_group("maxcut task")
    mc.add_argument("--grid", choices=["small", "large"], default="small", help="6-node or 12-node grid")
    mc.add_argument("--p", type=int, default=1, help="QAOA layers")

    fetch = sub.add_parser("fetch", help="collect the result of a job submitted earlier")
    fetch.add_argument("job_id")
    fetch.add_argument("--wait", action="store_true", help="block until the job finishes")

    args = ap.parse_args()
    {"devices": cmd_devices, "run": cmd_run, "fetch": cmd_fetch}[args.command](args)


if __name__ == "__main__":
    main()

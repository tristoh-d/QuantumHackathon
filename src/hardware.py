"""One hour on real hardware through qBraid (Milestone 5).

Rules from the track README:
- Tune on Aer first, then IonQ's free simulator with noise_model="forte-1".
- Run only the final, tuned circuit on hardware: p=1, at most 200 shots.
- Send hardware runs early (queues can take hours). Keep every job ID.
- Quantinuum's H2 emulator is a free second opinion; label it as an emulator.

Every qBraid run is appended to results/hardware_runs.csv so job IDs are never lost.
"""
import csv
import json
from datetime import datetime, timezone

import numpy as np

from src.config import MAX_HARDWARE_SHOTS, QPU_DEVICES, RESULTS_DIR

RUN_LOG = RESULTS_DIR / "hardware_runs.csv"
RUN_LOG_FIELDS = ["utc", "device", "kind", "job_id", "shots", "hour", "p", "cx_gates", "status", "counts_file", "note"]


def build_hardware_circuit(Q, angles, p=1):
    """Bind tuned angles into the QAOA circuit and add measurements. Returns (circuit, cx_count)."""
    from qiskit import QuantumCircuit, transpile

    from src.quantum import qaoa_circuit

    circuit, params = qaoa_circuit(Q, p=p)
    n = circuit.num_qubits
    qc = QuantumCircuit(n, n)
    qc.compose(circuit.assign_parameters(dict(zip(params, angles))), inplace=True)
    qc.measure(range(n), range(n))
    cx = transpile(qc, basis_gates=["rz", "sx", "x", "cx"]).count_ops().get("cx", 0)
    return qc, cx


def run_aer(qc, shots=200, seed=11):
    """Ideal (noise-free) local simulation. Returns Qiskit counts."""
    from qiskit import transpile
    from qiskit_aer import AerSimulator

    sim = AerSimulator()
    return sim.run(transpile(qc, sim), shots=shots, seed_simulator=seed).result().get_counts()


def device_kind(device_id):
    if device_id in QPU_DEVICES:
        return "QPU"
    if "emulator" in device_id:
        return "emulator"
    return "simulator"


def submit_qbraid(qc, device_id, shots=200, noise_model=None, allow_qpu=False):
    """Submit to a qBraid device. Returns the job (does not wait).

    QPU devices use credits: they are refused unless allow_qpu=True.
    """
    if shots > MAX_HARDWARE_SHOTS and device_id in QPU_DEVICES:
        raise ValueError(f"Hardware rule: at most {MAX_HARDWARE_SHOTS} shots per hardware run")
    if device_id in QPU_DEVICES and not allow_qpu:
        raise PermissionError(f"{device_id} is real hardware and uses credits. Pass allow_qpu=True "
                              "only for your final, tuned circuit.")
    import warnings

    from qbraid.runtime import QbraidProvider
    warnings.filterwarnings("ignore", message="Circuit contains measurement gates")  # IonQ measures all qubits

    device = QbraidProvider().get_device(device_id)
    runtime_options = {"noise_model": noise_model} if noise_model else None
    if runtime_options:
        return device.run(qc, shots=shots, runtime_options=runtime_options)
    return device.run(qc, shots=shots)


def log_run(device_id, job_id, shots, hour, p, cx_gates, status="submitted", counts=None, note=""):
    """Append one run to results/hardware_runs.csv (and save counts as JSON if given)."""
    RESULTS_DIR.mkdir(exist_ok=True)
    counts_file = ""
    if counts is not None:
        safe = str(job_id).replace(":", "_").replace("/", "_")
        counts_path = RESULTS_DIR / "counts" / f"{safe}.json"
        counts_path.parent.mkdir(exist_ok=True)
        counts_path.write_text(json.dumps(counts, indent=1))
        counts_file = str(counts_path.relative_to(RESULTS_DIR))
    new = not RUN_LOG.exists()
    with open(RUN_LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RUN_LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow(dict(utc=datetime.now(timezone.utc).isoformat(timespec="seconds"), device=device_id,
                        kind=device_kind(device_id), job_id=job_id, shots=shots, hour=hour, p=p,
                        cx_gates=cx_gates, status=status, counts_file=counts_file, note=note))


def choice_shares(counts, n_plants):
    """Share of shots for each on/off choice.

    int(key, 2) reads Qiskit's bitstring (qubit 0 is the last character) as an index,
    so bit j = qubit j; the low n_plants bits are the plants.
    """
    total = sum(counts.values())
    share = np.zeros(2 ** n_plants)
    for key, c in counts.items():
        share[int(key.replace(" ", ""), 2) & (2 ** n_plants - 1)] += c / total
    return share

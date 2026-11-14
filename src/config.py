"""Shared constants and the problem loader.

Everything that the upstream starter notebook kept as globals (plants, demand,
reserve, N, names, hours, COLORS) lives here so every module, script, test and
notebook uses the same values.
"""
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from src.check import load_demand, load_plants

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
RESULTS_DIR = REPO_ROOT / "results"

# Fleets: "5" is the main track, "10" is the stretch goal.
FLEETS = {
    "5": ("plants.csv", "demand.csv"),
    "10": ("plants10.csv", "demand10.csv"),
}

# QUBO encoding (see README "Milestone 3"): capacity is counted in 50 MW blocks,
# and the spare blocks are written in binary with N_SLACK helper bits.
# How many slack bits the 10-plant fleet needs is a stretch-goal question:
# pass n_slack explicitly instead of editing this default.
BLOCK_MW = 50
N_SLACK = 3

# Milestone 4: QAOA vs random guessing over these shot counts and seeds.
SHOT_GRID = (5, 10, 20, 50, 200)
N_SEEDS = 5

# Milestone 5: hardware rules from the track README.
MAX_HARDWARE_SHOTS = 200
DEVICES = {
    "ionq-sim": "ionq:ionq:sim:simulator",              # free, use with noise_model="forte-1"
    "ionq-qpu": "ionq:ionq:qpu:forte-1",                # real hardware, uses credits
    "ionq-qpu-aws": "aws:ionq:qpu:forte-1",             # fallback route to the same QPU (~1,630 credits / 200 shots)
    "quantinuum-emu": "quantinuum:quantinuum:sim:h2-emulator",  # free emulator, label as emulator
    "iqm-garnet": "aws:iqm:qpu:garnet",                 # backup; ask a qBraid mentor first
    "gpu-sv": "qbraid:qbraid:sim:gpu-sv",               # GPU statevector, up to 35 qubits
}
QPU_DEVICES = {"ionq:ionq:qpu:forte-1", "aws:ionq:qpu:forte-1", "aws:iqm:qpu:garnet"}

COLORS = {"milp": "#2a78d6", "qaoa": "#eb6834", "rule": "#1baf7a", "random": "#8a8984"}


@dataclass
class Problem:
    """One unit-commitment instance: a fleet of plants and a 24-hour demand curve."""
    plants: list
    demand: np.ndarray
    reserve: np.ndarray
    fleet: str = "5"
    names: list = field(init=False)

    def __post_init__(self):
        self.names = [p["plant_id"] for p in self.plants]

    @property
    def n(self) -> int:
        return len(self.plants)

    @property
    def hours(self) -> np.ndarray:
        return np.arange(len(self.demand))

    @property
    def start_state(self) -> list:
        return [int(p["on_at_start"]) for p in self.plants]


def load_problem(fleet: str = "5") -> Problem:
    """Load the 5-plant (default) or 10-plant fleet with its demand curve."""
    plants_file, demand_file = FLEETS[str(fleet)]
    plants = load_plants(DATA_DIR / plants_file)
    demand, reserve = load_demand(DATA_DIR / demand_file)
    return Problem(plants, demand, reserve, fleet=str(fleet))

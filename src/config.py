"""Shared constants and the problem loader.

Everything that the upstream starter notebook kept as globals (plants, demand,
reserve, N, names, hours, COLORS) lives here so every module, script, test and
notebook uses the same values.
"""
import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from src.check import load_demand, load_plants

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
RESULTS_DIR = REPO_ROOT / "results"


def load_env(path=REPO_ROOT / ".env"):
    """Read KEY=value lines from the repo's .env into os.environ (variables already set win).

    This is how a local run gets QBRAID_API_KEY; in qBraid Lab there is no .env and the
    account's own credentials are used.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


load_env()

# Fleets: "5" is the main track, "10" is the stretch goal, "tva" is the real TVA thermal fleet
# (20 plants, data/make_tva.py) with real EIA-930 net-load days (pick one with day=...).
FLEETS = {
    "5": ("plants.csv", "demand.csv"),
    "10": ("plants10.csv", "demand10.csv"),
    "tva": ("plants_tva.csv", "demand_tva/summer_weekday_0.csv"),
}
TVA_DAYS_DIR = DATA_DIR / "demand_tva"
TVA_META = DATA_DIR / "tva_meta.json"

# QUBO encoding (see README "Milestone 3"): capacity is counted in 50 MW blocks,
# and the spare blocks are written in binary with N_SLACK helper bits.
# How many slack bits the 10-plant fleet needs is a stretch-goal question:
# pass n_slack explicitly instead of editing this default.
BLOCK_MW = 50
N_SLACK = 3
# The QAOA and random samplers build tables with 2^n_qubits rows, so above ~20 qubits a laptop
# runs out of memory (the TVA fleet needs 25). Bigger problems: gpu-sv on qBraid, or a subset.
MAX_LOCAL_QUBITS = 20

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
    "rigetti-qpu-aws": "aws:rigetti:qpu:cepheus-1-108q",  # superconducting, cheap (~38.5 credits / 200 shots)
    "gpu-sv": "qbraid:qbraid:sim:gpu-sv",               # GPU statevector, up to 35 qubits
}
QPU_DEVICES = {"ionq:ionq:qpu:forte-1", "aws:ionq:qpu:forte-1", "aws:iqm:qpu:garnet",
               "aws:rigetti:qpu:cepheus-1-108q"}

COLORS = {"milp": "#2a78d6", "qaoa": "#eb6834", "rule": "#1baf7a", "random": "#8a8984"}


@dataclass
class Problem:
    """One unit-commitment instance: a fleet of plants and a 24-hour demand curve."""
    plants: list
    demand: np.ndarray
    reserve: np.ndarray
    fleet: str = "5"
    day: str = None                 # which demand day (TVA fleet only)
    block_mw: float = BLOCK_MW      # QUBO block size for this fleet
    n_slack: int = N_SLACK          # QUBO slack bits for this fleet
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

    @property
    def n_qubits(self) -> int:
        return self.n + self.n_slack

    def block_view(self) -> "Problem":
        """The same problem in units where one QUBO block is BLOCK_MW (50 MW).

        src/qubo.py counts capacity in fixed 50 MW blocks. For a fleet with a bigger block
        (TVA: 100 MW), every MW quantity is multiplied by s = BLOCK_MW / block_mw and marginal
        costs are divided by s, so every dollar amount is unchanged. pmax is first rounded to whole
        blocks (at least one). Schedules found on the view are valid 0/1 schedules for the
        real problem: score them with check_schedule on the original plants.
        """
        if self.block_mw == BLOCK_MW:
            return self
        s = BLOCK_MW / self.block_mw
        plants = []
        for p in self.plants:
            q = dict(p)
            blocks = max(1, round(p["pmax_mw"] / self.block_mw))
            q["pmax_mw"] = blocks * BLOCK_MW
            q["pmin_mw"] = min(p["pmin_mw"] * s, q["pmax_mw"])
            q["ramp_mw_per_h"] = p["ramp_mw_per_h"] * s
            q["marginal_cost_per_mwh"] = p["marginal_cost_per_mwh"] / s
            plants.append(q)
        return replace(self, plants=plants, demand=self.demand * s, reserve=self.reserve * s,
                       block_mw=BLOCK_MW)


def tva_meta() -> dict:
    return json.loads(TVA_META.read_text())


def tva_day_names() -> list:
    """Names of the saved TVA demand days (data/demand_tva/index.csv), e.g. 'summer_weekday_0', 'peak'."""
    import csv
    with open(TVA_DAYS_DIR / "index.csv", newline="") as f:
        return [r["name"] for r in csv.DictReader(f)]


def _tva_demand(day):
    """day: a saved-day name ('peak', 'summer_weekday_0'), an ISO date ('2024-07-15'),
    or 'sample:<season|any>:<daytype|any>:<seed>' to bootstrap one day from the pool."""
    from src import demand as tva
    if day.startswith("sample:"):
        _, season, daytype, seed = day.split(":")
        d = tva.sample_days(None if season == "any" else season, None if daytype == "any" else daytype,
                            n=1, seed=int(seed))[0]
        return d.demand.astype(float), d.reserve.astype(float), f"{day} ({d.date})"
    path = TVA_DAYS_DIR / f"{day}.csv"
    if path.exists():
        demand, reserve = load_demand(path)
        return demand, reserve, day
    d = tva.get_day(day)
    return d.demand.astype(float), d.reserve.astype(float), day


def load_problem(fleet: str = "5", day: str = None) -> Problem:
    """Load a fleet ("5" default, "10", or "tva") with its demand curve.

    day (TVA fleet only) picks the demand day: see _tva_demand. Default: summer_weekday_0.
    """
    fleet = str(fleet)
    plants_file, demand_file = FLEETS[fleet]
    plants = load_plants(DATA_DIR / plants_file)
    if fleet != "tva":
        if day is not None:
            raise ValueError("day= is only available for the 'tva' fleet")
        demand, reserve = load_demand(DATA_DIR / demand_file)
        return Problem(plants, demand, reserve, fleet=fleet)
    demand, reserve, label = _tva_demand(day or Path(demand_file).stem)
    meta = tva_meta()["plants"]
    return Problem(plants, demand, reserve, fleet=fleet, day=label,
                   block_mw=meta["block_mw"], n_slack=meta["n_slack"])

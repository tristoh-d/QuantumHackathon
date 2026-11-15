"""DC power flow on the 3-area RTS-GMLC grid (the "simulation" inside the QPE / HHL approach).

Paper: Stein et al., "Exponential Quantum Speedup for Simulation-Based Optimization Applications",
arXiv:2305.08482, Def. 7 (power-flow focused unit commitment). Notation follows the paper:

    B      Laplacian of the grid, weighted by line susceptances b_ij (per unit, 100 MVA base)
    B_bar  B with the reference bus row and column removed (invertible, Lem. 15)
    p_bar  net injection at each non-reference bus (per unit)
    theta  bus voltage angles:  B_bar theta = p_bar   (theta_ref = 0)
    flow   on line (i, j):      rho_ij = b_ij (theta_i - theta_j)

Grid (data/network_rts3.csv, built by data/make_network.py): one node per RTS-GMLC area, with
equivalent tie lines. A plant sits in the area of its RTS bus (first digit of rts_gen_uid). The
whole demand is in area C, because the demand curve is RTS-GMLC region 3 load (data/README.md).
Area C is the reference bus.

Transmission cost of an hour = sum over lines of cost_per_mwh * |flow| (paper: <c, |rho_x|>).
"""
import csv
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from src.check import dispatch_hour
from src.config import DATA_DIR

NETWORK_CSV = DATA_DIR / "network_rts3.csv"
BASE_MVA = 100.0
AREA_OF_DIGIT = {"1": "A", "2": "B", "3": "C"}


@dataclass(frozen=True)
class Network:
    areas: tuple            # ("A", "B", "C")
    ref: str                # reference bus (holds the load)
    lines: tuple            # ((i, j, b_pu, rating_mw, cost_per_mwh), ...) with area indices i < j

    @property
    def n_bus(self):
        return len(self.areas)

    @property
    def laplacian(self):
        B = np.zeros((self.n_bus, self.n_bus))
        for i, j, b, _, _ in self.lines:
            B[i, i] += b
            B[j, j] += b
            B[i, j] -= b
            B[j, i] -= b
        return B

    @property
    def keep(self):
        """Indices of the non-reference buses (the rows of B_bar)."""
        r = self.areas.index(self.ref)
        return [k for k in range(self.n_bus) if k != r]

    @property
    def B_bar(self):
        k = self.keep
        return self.laplacian[np.ix_(k, k)]

    @property
    def line_matrix(self):
        """F with flows_pu = F @ theta_bar: row e = b_ij (e_i - e_j), reference column dropped."""
        F = np.zeros((len(self.lines), self.n_bus))
        for e, (i, j, b, _, _) in enumerate(self.lines):
            F[e, i], F[e, j] = b, -b
        return F[:, self.keep]

    @property
    def costs(self):
        return np.array([c for *_, c in self.lines])

    @property
    def ratings(self):
        return np.array([r for _, _, _, r, _ in self.lines])

    def line_names(self):
        return [f"{self.areas[i]}-{self.areas[j]}" for i, j, *_ in self.lines]


@lru_cache(maxsize=None)
def load_network(path=NETWORK_CSV, cost_per_mwh=None) -> Network:
    """The 3-area grid. cost_per_mwh overrides the CSV's transmission price on every line."""
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    areas = tuple(sorted({r["from_area"] for r in rows} | {r["to_area"] for r in rows}))
    lines = tuple((areas.index(r["from_area"]), areas.index(r["to_area"]), float(r["susceptance_pu"]),
                   float(r["rating_mw"]), float(r["cost_per_mwh"]) if cost_per_mwh is None else cost_per_mwh)
                  for r in rows)
    return Network(areas=areas, ref="C", lines=lines)


def plant_areas(plants, net: Network):
    """Area index of each plant, from the bus number in its RTS-GMLC unit ID."""
    return [net.areas.index(AREA_OF_DIGIT[p["rts_gen_uid"][0]]) for p in plants]


def injections_mw(plants, demand_mw, on, net: Network):
    """Net injection (MW) at every area: economic dispatch of the plants that are on, minus the load."""
    out, _ = dispatch_hour(plants, demand_mw, on)
    p = np.zeros(net.n_bus)
    for a, mw in zip(plant_areas(plants, net), out):
        p[a] += mw
    p[net.areas.index(net.ref)] -= demand_mw
    return p


def p_bar_pu(p_mw, net: Network):
    """Reduced injection vector in per unit (reference bus dropped)."""
    return np.asarray(p_mw)[net.keep] / BASE_MVA


def solve_angles(p_bar, net: Network):
    """Classical DC power flow: theta_bar = B_bar^-1 p_bar."""
    return np.linalg.solve(net.B_bar, p_bar)


def flows_mw(theta_bar, net: Network):
    return net.line_matrix @ theta_bar * BASE_MVA


def transmission_cost(flows, net: Network):
    """<c, |rho|> in $ for one hour."""
    return float(net.costs @ np.abs(flows))


def hour_network(plants, demand_mw, on, net: Network):
    """Flows (MW) and transmission cost ($) of one hour's on/off choice, with merit-order dispatch."""
    f = flows_mw(solve_angles(p_bar_pu(injections_mw(plants, demand_mw, on, net), net), net), net)
    return f, transmission_cost(f, net)


def day_network(plants, demand, schedule, net: Network):
    """Transmission cost of a whole day ($), the hourly flows, and any flow above a line's rating."""
    total, all_flows, overloads = 0.0, [], []
    for t, on in enumerate(schedule):
        f, c = hour_network(plants, demand[t], on, net)
        total += c
        all_flows.append(f)
        for name, mw, rating in zip(net.line_names(), f, net.ratings):
            if abs(mw) > rating + 1e-6:
                overloads.append((t, name, float(mw), float(rating)))
    return total, np.array(all_flows), overloads

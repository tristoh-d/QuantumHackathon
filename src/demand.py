"""TVA demand days: a pool of real days from EIA-930, bootstrapping, and the QAOA block layout.

The pool is data/tva_hourly.csv (built by data/make_tva.py, committed). Each day is the TVA
balancing authority's hourly net load: demand minus nuclear, hydro (incl. pumped storage),
wind, solar and other non-thermal output. That is what the thermal fleet in plants_tva.csv
must cover. Only days the fleet can cover (max of net load + reserve <= its capacity) are in the pool.

    from src.demand import sample_days
    days = sample_days("summer", "weekday", n=10, seed=3)    # 10 real summer weekdays
    days[0].demand, days[0].reserve                          # arrays of 24 values, MW

Bootstrapping = drawing whole real days at random (with replacement by default) inside a
stratum (season x weekday/weekend). The same seed always gives the same days.
"""
import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
HOURLY = DATA_DIR / "tva_hourly.csv"
PLANTS = DATA_DIR / "plants_tva.csv"
SEASON_ORDER = ("winter", "spring", "summer", "fall")
DAYTYPES = ("weekday", "weekend")
RESERVE = 0.10


@dataclass(frozen=True)
class DemandDay:
    """One 24-hour day. demand = thermal net load (MW), reserve = 10% of it."""
    date: str
    season: str
    daytype: str
    demand: np.ndarray
    reserve: np.ndarray

    def scaled(self, factor: float) -> "DemandDay":
        d = np.round(self.demand * factor)
        return DemandDay(self.date, self.season, self.daytype, d, np.round(RESERVE * d))


# ---------------------------------------------------------------- pool
@lru_cache(maxsize=None)
def _all_days(path=HOURLY):
    """Every day in tva_hourly.csv, feasible or not, in date order."""
    by_date = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            by_date.setdefault(r["date"], (r["season"], r["daytype"], []))[2].append(float(r["net_load_mw"]))
    days = []
    for date, (season, daytype, net) in sorted(by_date.items()):
        demand = np.array(net)
        days.append(DemandDay(date, season, daytype, demand, np.round(RESERVE * demand)))
    return tuple(days)


@lru_cache(maxsize=None)
def fleet_capacity(path=PLANTS) -> float:
    with open(path, newline="") as f:
        return sum(float(r["pmax_mw"]) for r in csv.DictReader(f))


def feasible(day: DemandDay, capacity: float) -> bool:
    return float((day.demand + day.reserve).max()) <= capacity


@lru_cache(maxsize=None)
def tva_day_pool(capacity=None):
    """Days the TVA thermal fleet can cover (default capacity: sum of pmax in plants_tva.csv)."""
    cap = fleet_capacity() if capacity is None else capacity
    return tuple(d for d in _all_days() if feasible(d, cap))


def stratum(season=None, daytype=None, pool=None):
    pool = tva_day_pool() if pool is None else pool
    for name, value, allowed in (("season", season, SEASON_ORDER), ("daytype", daytype, DAYTYPES)):
        if value is not None and value not in allowed:
            raise ValueError(f"{name} must be one of {allowed}, got {value!r}")
    return [d for d in pool if (season is None or d.season == season) and (daytype is None or d.daytype == daytype)]


# ---------------------------------------------------------------- generator
def sample_days(season=None, daytype=None, n=1, seed=0, replace=True, scale_to=None):
    """Bootstrap n real days from one stratum (None = any season / any day type).

    replace=False draws n different days. scale_to=<MW> rescales every day linearly so that
    the TVA fleet's capacity maps to scale_to (for running TVA load shapes on a smaller fleet).
    """
    days = stratum(season, daytype)
    if not days:
        raise ValueError(f"no feasible days for season={season}, daytype={daytype}")
    rng = np.random.default_rng(seed)
    picks = rng.choice(len(days), size=n, replace=replace)
    out = [days[k] for k in picks]
    if scale_to is not None:
        out = [d.scaled(scale_to / fleet_capacity()) for d in out]
    return out


def get_day(date: str) -> DemandDay:
    """The pool day with this ISO date (YYYY-MM-DD)."""
    for d in tva_day_pool():
        if d.date == date:
            return d
    raise KeyError(f"{date} is not in the feasible TVA day pool")


def extreme_days():
    """The pool days with the highest peak and the lowest minimum net load (stress cases)."""
    pool = tva_day_pool()
    return {"peak": max(pool, key=lambda d: d.demand.max()), "min": min(pool, key=lambda d: d.demand.min())}


def pool_stats():
    """Day counts: all days, feasible days, and feasible days per stratum."""
    pool = tva_day_pool()
    return dict(days_total=len(_all_days()), days_feasible=len(pool),
                days_infeasible=len(_all_days()) - len(pool),
                capacity_mw=fleet_capacity(),
                per_stratum={f"{s}_{t}": len(stratum(s, t)) for s in SEASON_ORDER for t in DAYTYPES})


def write_demand_csv(path, day: DemandDay):
    """Same format as data/demand.csv, so src.check.load_demand reads it."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["hour", "demand_mw", "reserve_mw"])
        for t, (d, r) in enumerate(zip(day.demand, day.reserve)):
            w.writerow([t, int(d), int(r)])


# ---------------------------------------------------------------- QAOA blocks
def block_layout(pmax_list, block_mw):
    """(blocks per plant, slack bits) when capacity is counted in block_mw blocks.

    Every plant gets at least one block. The slack bits must cover the spare blocks of a good
    choice, which is less than the largest plant's blocks; for the 5-plant fleet (blocks
    7, 7, 1, 1, 1) this gives 3 bits, the repo's N_SLACK.
    """
    blocks = [max(1, round(p / block_mw)) for p in pmax_list]
    return blocks, max(blocks).bit_length()

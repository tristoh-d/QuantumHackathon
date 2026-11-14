"""Checker for the TVA plant-scheduling track (unit commitment).

From the notebook:

    from check import load_plants, load_demand, check_schedule, check_hour, solve_milp

As a script, for a short demo:  python check.py

A schedule is a 0/1 array with one row per hour and one column per plant:
schedule[t, i] = 1 means plant i is on during hour t.
"""
import csv
import time
from itertools import product
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

DATA = Path(__file__).resolve().parent / "data"
TEXT_COLUMNS = ("plant_id", "type", "rts_gen_uid")


# ------------------------------------------------------------------ loading
def load_plants(path=DATA / "plants.csv"):
    """List of plants: one dict per row of plants.csv (numbers become floats)."""
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return [{k: (v if k in TEXT_COLUMNS else float(v)) for k, v in r.items()} for r in rows]


def load_demand(path=DATA / "demand.csv"):
    """Two arrays with one value per hour: demand_mw and reserve_mw."""
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return (np.array([float(r["demand_mw"]) for r in rows]),
            np.array([float(r["reserve_mw"]) for r in rows]))


# ------------------------------------------------------------------ one hour
def dispatch_hour(plants, demand_mw, on):
    """Economic dispatch: the cheapest output for each plant that is on.

    Every plant that is on makes at least pmin. The rest of the demand goes to the
    cheapest plants first (merit order). Returns (outputs_mw, shortfall_mw):
    shortfall > 0 means not enough capacity, < 0 means the minimum outputs exceed demand.
    """
    out = np.array([p["pmin_mw"] * u for p, u in zip(plants, on)], dtype=float)
    left = demand_mw - out.sum()
    for i in sorted(range(len(plants)), key=lambda i: plants[i]["marginal_cost_per_mwh"]):
        if on[i] and left > 0:
            extra = min(left, plants[i]["pmax_mw"] - plants[i]["pmin_mw"])
            out[i] += extra
            left -= extra
    return out, left


def hour_cost(plants, demand_mw, on, was_on):
    """Exact cost of one hour: startups + no-load + energy (after economic dispatch)."""
    out, _ = dispatch_hour(plants, demand_mw, on)
    cost = 0.0
    for p, u, w, mw in zip(plants, on, was_on, out):
        if u:
            cost += p["no_load_cost_per_h"] + p["marginal_cost_per_mwh"] * mw
            if not w:
                cost += p["startup_cost"]
    return cost


def hour_ok(plants, demand_mw, reserve_mw, on, must_on=(), must_off=()):
    """True if on/off choice `on` meets demand and reserve and respects the locks."""
    cap = sum(p["pmax_mw"] * u for p, u in zip(plants, on))
    floor = sum(p["pmin_mw"] * u for p, u in zip(plants, on))
    locks_ok = all(on[i] for i in must_on) and not any(on[i] for i in must_off)
    return cap >= demand_mw + reserve_mw and floor <= demand_mw and locks_ok


def locks(plants, history):
    """Plants that min up / min down times force to stay on or off next hour.

    history: list of the on/off choices made so far (one list per hour).
    Returns (must_on, must_off) as lists of plant indices.
    The state at midnight is assumed to have lasted long enough to switch freely.
    """
    must_on, must_off = [], []
    for i, p in enumerate(plants):
        states = [int(p["on_at_start"])] + [int(h[i]) for h in history]
        now, held = states[-1], 0
        for s in reversed(states):
            if s != now:
                break
            held += 1
        if held == len(states):          # never switched today
            continue
        if now == 1 and held < p["min_up_h"]:
            must_on.append(i)
        if now == 0 and held < p["min_down_h"]:
            must_off.append(i)
    return must_on, must_off


def check_hour(plants, demand_mw, reserve_mw, choice, was_on=None, must_on=(), must_off=(),
               verbose=True):
    """Score one hour's on/off choice, and say whether it is the best of all 2^n choices.

    The printout tells you "Match!" or "Not the best choice yet." without showing the best choice.
    The returned dict still has best_choice and best_cost, for code that needs them.

    was_on: last hour's on/off (decides who pays a startup). Default: on_at_start.
    must_on / must_off: plant indices locked by min up / min down times (see locks()).
    """
    if was_on is None:
        was_on = [int(p["on_at_start"]) for p in plants]
    choice = [int(x) for x in choice]
    best, best_cost = None, np.inf
    for on in product([0, 1], repeat=len(plants)):
        if hour_ok(plants, demand_mw, reserve_mw, on, must_on, must_off):
            c = hour_cost(plants, demand_mw, on, was_on)
            if c < best_cost:
                best, best_cost = list(on), c
    valid = hour_ok(plants, demand_mw, reserve_mw, choice, must_on, must_off)
    cost = hour_cost(plants, demand_mw, choice, was_on)
    result = dict(valid=valid, cost=cost, best_choice=best, best_cost=best_cost,
                  matches_best=bool(valid and best is not None and np.isclose(cost, best_cost)))
    if verbose:
        names = lambda on: "+".join(p["plant_id"] for p, u in zip(plants, on) if u) or "none"
        status = "valid" if valid else "NOT valid (demand, reserve or a lock is broken)"
        print(f"Your choice: {names(choice)}  ->  {status}, cost ${cost:,.0f}")
        if best is None:
            print("No choice meets demand, reserve and the locks this hour.")
        else:
            print("Match!" if result["matches_best"] else "Not the best choice yet.")
    return result


# ------------------------------------------------------------------ a whole day
def check_schedule(plants, demand, reserve, schedule, milp_cost=None, ramps=False, verbose=True):
    """Score a schedule (hours x plants, 0/1): cost, rules broken and, if you pass milp_cost, the gap.

    Returns a dict: valid, total_cost (startup + no-load + energy), the three cost parts,
    violations (hour, plant, rule, detail), dispatch, and gap_pct vs milp_cost when you pass one
    (None otherwise). It doesn't solve the MILP for you. ramps=True also checks ramp limits.
    """
    s = np.asarray(schedule).astype(int)
    T, n = s.shape
    prev = np.array([int(p["on_at_start"]) for p in plants])
    violations, outputs = [], np.zeros((T, n))
    startup = noload = energy = 0.0
    for t in range(T):
        out, short = dispatch_hour(plants, demand[t], s[t])
        outputs[t] = out
        cap = sum(p["pmax_mw"] * u for p, u in zip(plants, s[t]))
        if short > 1e-6:
            violations.append((t, "-", "demand not met", f"short by {short:.0f} MW"))
        if short < -1e-6:
            violations.append((t, "-", "demand not met",
                               f"minimum outputs exceed demand by {-short:.0f} MW"))
        if cap < demand[t] + reserve[t] - 1e-6:
            violations.append((t, "-", "reserve not met",
                               f"capacity {cap:.0f} MW < demand + reserve {demand[t] + reserve[t]:.0f} MW"))
        for i, p in enumerate(plants):
            if s[t, i]:
                noload += p["no_load_cost_per_h"]
                energy += p["marginal_cost_per_mwh"] * out[i]
                startup += p["startup_cost"] * (1 - prev[i])
        prev = s[t]
    violations += _min_up_down_violations(plants, s)
    if ramps:
        violations += _ramp_violations(plants, s, outputs)
    violations.sort(key=lambda v: v[0])
    total = startup + noload + energy
    gap = None if milp_cost is None else 100 * (total - milp_cost) / milp_cost
    result = dict(valid=not violations, total_cost=total, startup_cost=startup,
                  no_load_cost=noload, energy_cost=energy, milp_cost=milp_cost,
                  gap_pct=None if gap is None else (0.0 if abs(gap) < 1e-6 else gap),
                  violations=violations, dispatch=outputs)
    if verbose:
        print_report(result)
    return result


def _min_up_down_violations(plants, s):
    """A plant that switches must have held its old state for min_up_h / min_down_h."""
    found = []
    for i, p in enumerate(plants):
        prev, since = int(p["on_at_start"]), None      # since = hour of the last switch
        for t in range(s.shape[0]):
            if s[t, i] != prev:
                if since is not None:
                    held = t - since
                    if prev == 1 and held < p["min_up_h"]:
                        found.append((t, p["plant_id"], "min up broken",
                                      f"turned off after {held} h on (needs {p['min_up_h']:.0f})"))
                    if prev == 0 and held < p["min_down_h"]:
                        found.append((t, p["plant_id"], "min down broken",
                                      f"restarted after {held} h off (needs {p['min_down_h']:.0f})"))
                prev, since = s[t, i], t
    return found


def _ramp_violations(plants, s, outputs):
    found = []
    for t in range(1, s.shape[0]):
        for i, p in enumerate(plants):
            step = abs(outputs[t, i] - outputs[t - 1, i])
            if s[t, i] and s[t - 1, i] and step > p["ramp_mw_per_h"] + 1e-6:
                found.append((t, p["plant_id"], "ramp broken", f"changed {step:.0f} MW in 1 h"))
    return found


def print_report(r):
    print(f"Total cost: ${r['total_cost']:,.0f}  (startups ${r['startup_cost']:,.0f}, "
          f"no-load ${r['no_load_cost']:,.0f}, energy ${r['energy_cost']:,.0f})")
    if r["milp_cost"] is not None:
        print(f"MILP optimum: ${r['milp_cost']:,.0f}   gap: {r['gap_pct']:+.2f}%")
    if r["valid"]:
        print("Valid: every hour meets demand and reserve; no min up/down rule is broken.")
    else:
        print(f"NOT valid: {len(r['violations'])} rule(s) broken")
        print(f"  {'hour':>4}  {'plant':<10} {'rule':<16} detail")
        for t, pid, rule, detail in r["violations"]:
            print(f"  {t:>4}  {pid:<10} {rule:<16} {detail}")


# ------------------------------------------------------------------ classical baseline
def solve_milp(plants, demand, reserve, ramps=False):
    """Optimal schedule from a mixed-integer program (scipy milp, HiGHS solver).

    Variables for each plant i and hour t: u (on/off), v (started this hour), p (MW).
    Minimize   sum no_load*u + startup*v + marginal_cost*p
    subject to demand, reserve, pmin*u <= p <= pmax*u, startup logic, min up / min down
    (and ramp limits if ramps=True).
    Returns (cost, schedule [hours x plants], dispatch [hours x plants], seconds).
    """
    n, T = len(plants), len(demand)
    U = lambda i, t: i * T + t
    V = lambda i, t: n * T + i * T + t
    P = lambda i, t: 2 * n * T + i * T + t
    cost = np.zeros(3 * n * T)
    for i, p in enumerate(plants):
        for t in range(T):
            cost[U(i, t)] = p["no_load_cost_per_h"]
            cost[V(i, t)] = p["startup_cost"]
            cost[P(i, t)] = p["marginal_cost_per_mwh"]
    rows, lo, hi = [], [], []

    def add(terms, low, high):            # low <= sum(coef * x[j]) <= high
        rows.append(terms)
        lo.append(low)
        hi.append(high)

    for t in range(T):
        add([(P(i, t), 1) for i in range(n)], demand[t], demand[t])
        add([(U(i, t), p["pmax_mw"]) for i, p in enumerate(plants)], demand[t] + reserve[t], np.inf)
    for i, p in enumerate(plants):
        up, down, u0 = int(p["min_up_h"]), int(p["min_down_h"]), int(p["on_at_start"])
        for t in range(T):
            add([(P(i, t), 1), (U(i, t), -p["pmin_mw"])], 0, np.inf)
            add([(P(i, t), 1), (U(i, t), -p["pmax_mw"])], -np.inf, 0)
            before = [(U(i, t - 1), 1)] if t > 0 else []          # v_t >= u_t - u_(t-1)
            add([(V(i, t), 1), (U(i, t), -1)] + before, -u0 if t == 0 else 0, np.inf)
            # min up: a start in the last `up` hours means the plant is still on
            add([(V(i, s), 1) for s in range(max(0, t - up + 1), t + 1)] + [(U(i, t), -1)],
                -np.inf, 0)
            # min down: no start in the last `down` hours if the plant was on before them
            window = [(V(i, s), 1) for s in range(max(0, t - down + 1), t + 1)]
            if t - down >= 0:
                add(window + [(U(i, t - down), 1)], -np.inf, 1)
            else:
                add(window, -np.inf, 1 - u0)
            if ramps and t > 0:
                r, big = p["ramp_mw_per_h"], p["pmax_mw"]
                add([(P(i, t), 1), (P(i, t - 1), -1), (U(i, t - 1), big)], -np.inf, r + big)
                add([(P(i, t - 1), 1), (P(i, t), -1), (U(i, t), big)], -np.inf, r + big)
    A = lil_matrix((len(rows), 3 * n * T))
    for k, terms in enumerate(rows):
        for j, a in terms:
            A[k, j] += a
    integrality = np.r_[np.ones(2 * n * T), np.zeros(n * T)]
    upper = np.r_[np.ones(2 * n * T), [p["pmax_mw"] for p in plants for _ in range(T)]]
    start = time.perf_counter()
    res = milp(cost, constraints=LinearConstraint(A.tocsr(), lo, hi),
               integrality=integrality, bounds=Bounds(0, upper))
    seconds = time.perf_counter() - start
    if res.x is None:
        raise RuntimeError(f"The MILP found no schedule: {res.message}")
    schedule = np.array([[round(res.x[U(i, t)]) for i in range(n)] for t in range(T)])
    dispatch = np.array([[res.x[P(i, t)] for i in range(n)] for t in range(T)])
    return res.fun, schedule, dispatch, seconds


# ------------------------------------------------------------------ demo
if __name__ == "__main__":
    plants = load_plants()
    demand, reserve = load_demand()
    best, schedule, _, secs = solve_milp(plants, demand, reserve)
    print(f"MILP solved {len(plants)} plants x {len(demand)} hours in {secs:.3f} s\n")

    print("A schedule with every plant on all day:")
    check_schedule(plants, demand, reserve, np.ones_like(schedule))

    print("\nOne hour (hour 12, coal and gas CC were on at hour 11), only COAL + GAS_CC on:")
    check_hour(plants, demand[12], reserve[12], [1, 1, 0, 0, 0], was_on=[1, 1, 0, 0, 0])

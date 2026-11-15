"""Classical baseline for the network-aware problem: the organizers' MILP plus DC power flow and line costs.

The formulation is the one of src/check.solve_milp (copied here because check.py is read-only), with
two additions per hour t and tie line e:

    flow_e,t = sum_i H[e, area(i)] * p_i,t        H = F B_bar^-1  (power transfer factors, MW per MW)
    s_e,t >= +flow_e,t,   s_e,t >= -flow_e,t      (s_e,t = |flow_e,t| at the optimum)
    objective += cost_per_mwh_e * s_e,t

The whole load sits at the reference area C, so it adds nothing to the non-reference injections.
Unlike the hour-by-hour methods, the MILP also chooses the dispatch, so it may shift output to save
transmission cost. Line ratings are not enforced (report only, as in the QPE approach).
"""
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from src.network import Network, plant_areas


def transfer_factors(net: Network):
    """H[e, k]: MW on line e per MW injected at non-reference area k (and taken out at the reference)."""
    return net.line_matrix @ np.linalg.inv(net.B_bar)


def solve_network_milp(plants, demand, reserve, net: Network, buses=None, load_share=None):
    """Returns dict(cost, generation_cost, transmission_cost, schedule, dispatch, flows, seconds, nodes).

    buses:      bus index of each plant (default: its RTS area, plant_areas).
    load_share: fraction of the demand at each bus (default: all of it at the reference bus).
    """
    n, T, L = len(plants), len(demand), len(net.lines)
    U = lambda i, t: i * T + t
    V = lambda i, t: n * T + i * T + t
    P = lambda i, t: 2 * n * T + i * T + t
    S = lambda e, t: 3 * n * T + e * T + t
    nvar = 3 * n * T + L * T
    cost = np.zeros(nvar)
    for i, p in enumerate(plants):
        for t in range(T):
            cost[U(i, t)] = p["no_load_cost_per_h"]
            cost[V(i, t)] = p["startup_cost"]
            cost[P(i, t)] = p["marginal_cost_per_mwh"]
    for e in range(L):
        for t in range(T):
            cost[S(e, t)] = net.costs[e]
    rows, lo, hi = [], [], []

    def add(terms, low, high):
        rows.append(terms)
        lo.append(low)
        hi.append(high)

    # --- same constraints as src/check.solve_milp (ramps off)
    for t in range(T):
        add([(P(i, t), 1) for i in range(n)], demand[t], demand[t])
        add([(U(i, t), p["pmax_mw"]) for i, p in enumerate(plants)], demand[t] + reserve[t], np.inf)
    for i, p in enumerate(plants):
        up, down, u0 = int(p["min_up_h"]), int(p["min_down_h"]), int(p["on_at_start"])
        for t in range(T):
            add([(P(i, t), 1), (U(i, t), -p["pmin_mw"])], 0, np.inf)
            add([(P(i, t), 1), (U(i, t), -p["pmax_mw"])], -np.inf, 0)
            before = [(U(i, t - 1), 1)] if t > 0 else []
            add([(V(i, t), 1), (U(i, t), -1)] + before, -u0 if t == 0 else 0, np.inf)
            add([(V(i, s), 1) for s in range(max(0, t - up + 1), t + 1)] + [(U(i, t), -1)], -np.inf, 0)
            window = [(V(i, s), 1) for s in range(max(0, t - down + 1), t + 1)]
            if t - down >= 0:
                add(window + [(U(i, t - down), 1)], -np.inf, 1)
            else:
                add(window, -np.inf, 1 - u0)
    # --- network: s >= |flow|
    H = transfer_factors(net)
    keep = net.keep
    areas = plant_areas(plants, net) if buses is None else list(buses)
    share = np.zeros(net.n_bus) if load_share is None else np.asarray(load_share, dtype=float)
    load_flow = H @ share[keep]                       # MW on each line per MW of total demand
    for e in range(L):
        for t in range(T):
            flow = [(P(i, t), H[e, keep.index(a)]) for i, a in enumerate(areas) if a in keep]
            d = demand[t] * load_flow[e]              # flow_e,t = sum H p - d
            add([(S(e, t), 1)] + [(j, -h) for j, h in flow], -d, np.inf)    # s - flow >= 0
            add([(S(e, t), 1)] + [(j, h) for j, h in flow], d, np.inf)      # s + flow >= 0

    A = lil_matrix((len(rows), nvar))
    for k, terms in enumerate(rows):
        for j, a in terms:
            A[k, j] += a
    integrality = np.r_[np.ones(2 * n * T), np.zeros(n * T + L * T)]
    upper = np.r_[np.ones(2 * n * T), [p["pmax_mw"] for p in plants for _ in range(T)], np.full(L * T, np.inf)]
    start = time.perf_counter()
    res = milp(cost, constraints=LinearConstraint(A.tocsr(), lo, hi), integrality=integrality,
               bounds=Bounds(0, upper))
    seconds = time.perf_counter() - start
    if res.x is None:
        raise RuntimeError(f"The network MILP found no schedule: {res.message}")
    x = res.x
    schedule = np.array([[round(x[U(i, t)]) for i in range(n)] for t in range(T)])
    dispatch = np.array([[x[P(i, t)] for i in range(n)] for t in range(T)])
    flows = np.array([[sum(H[e, keep.index(a)] * dispatch[t, i] for i, a in enumerate(areas) if a in keep)
                       - demand[t] * load_flow[e] for e in range(L)] for t in range(T)])
    transmission = float(sum(net.costs[e] * abs(flows[t, e]) for e in range(L) for t in range(T)))
    return dict(cost=float(res.fun), generation_cost=float(res.fun) - transmission, transmission_cost=transmission,
                schedule=schedule, dispatch=dispatch, flows=flows, seconds=seconds,
                nodes=int(getattr(res, "mip_node_count", -1) or -1))


def total_cost(problem, schedule, net: Network):
    """Generation cost (checker, merit-order dispatch) + transmission cost of that dispatch, for any schedule."""
    from src.check import check_schedule
    from src.network import day_network
    r = check_schedule(problem.plants, problem.demand, problem.reserve, schedule, verbose=False)
    trans, flows, overloads = day_network(problem.plants, problem.demand, schedule, net)
    return dict(valid=r["valid"], generation_cost=r["total_cost"], transmission_cost=trans,
                total=r["total_cost"] + trans, violations=r["violations"], overloads=overloads, flows=flows)

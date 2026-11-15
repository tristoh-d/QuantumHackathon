"""Classical look-ahead for the hybrid QAOA scheduler.

The hour-by-hour loop (src/scheduler.py) keeps the sampled choice that is cheapest *this hour*.
That is short-sighted: it skips a startup that would pay for itself later, or turns on a plant
whose min up time then forces expensive hours. docs/results.md traces most of the gap to the
MILP to this.

The look-ahead keeps QAOA as the proposer and changes how a proposal is judged:

    score(c) = cost of hours 0..t with c at hour t  +  best cost of hours t+1 .. t+H

The second term is a small MILP over the next H hours, solved with every hour up to t fixed
(the schedule so far plus candidate c). Fixing the past inside the same formulation as the
organizers' solve_milp (src/check.py) makes min up / min down times work exactly as in the
full-day MILP. A candidate that leads to a dead end (no valid way to continue) scores inf.

The cost of hours 0..t-1 is the same for every candidate at hour t, so ranking by score is the
same as ranking by "this hour + the next H hours". H=0 is the plain hour-by-hour rule; H large
enough to reach the end of the day turns the step into "which proposal is best for the rest of
the day". The formulation is the one in src/check.py (u on/off, v start, p MW per plant-hour),
rebuilt here because check.py is read-only and has no way to fix hours.
"""
from functools import lru_cache

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix


class Lookahead:
    """Scores on/off choices for hour t by this hour plus the optimal next `horizon` hours.

    One instance per (plants, demand, reserve). Constraint matrices are cached by the number of
    hours in the window, so a whole day needs at most 24 matrix builds.
    """

    def __init__(self, plants, demand, reserve, horizon):
        self.plants = plants
        self.demand = np.asarray(demand, dtype=float)
        self.reserve = np.asarray(reserve, dtype=float)
        self.horizon = int(horizon)
        self.n = len(plants)
        self.solves = 0
        self.seconds = 0.0
        self._model = lru_cache(maxsize=None)(self._build)

    # ------------------------------------------------------------ model for hours 0..T-1
    def _build(self, T):
        n, plants = self.n, self.plants
        U = lambda i, t: i * T + t
        V = lambda i, t: n * T + i * T + t
        P = lambda i, t: 2 * n * T + i * T + t
        cost = np.zeros(3 * n * T)
        for i, p in enumerate(plants):
            cost[[U(i, t) for t in range(T)]] = p["no_load_cost_per_h"]
            cost[[V(i, t) for t in range(T)]] = p["startup_cost"]
            cost[[P(i, t) for t in range(T)]] = p["marginal_cost_per_mwh"]
        r, c, a, lo, hi = [], [], [], [], []
        demand_rows, reserve_rows = [], []

        def add(terms, low, high):
            k = len(lo)
            for j, v in terms:
                r.append(k), c.append(j), a.append(v)
            lo.append(low), hi.append(high)
            return k

        for t in range(T):                                   # bounds filled in per call
            demand_rows.append(add([(P(i, t), 1) for i in range(n)], 0, 0))
            reserve_rows.append(add([(U(i, t), p["pmax_mw"]) for i, p in enumerate(plants)], 0, np.inf))
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
        A = coo_matrix((a, (r, c)), shape=(len(lo), 3 * n * T)).tocsr()
        integrality = np.r_[np.ones(2 * n * T), np.zeros(n * T)]
        upper = np.r_[np.ones(2 * n * T), [p["pmax_mw"] for p in plants for _ in range(T)]]
        return dict(T=T, cost=cost, A=A, lo=np.array(lo, dtype=float), hi=np.array(hi, dtype=float),
                    demand_rows=np.array(demand_rows), reserve_rows=np.array(reserve_rows),
                    integrality=integrality, upper=upper)

    # ------------------------------------------------------------ scoring
    def _solve(self, history, t, pins):
        """MILP over hours 0..t+H with `history` fixing hours 0..t-1 and `pins` {(plant, hour): 0/1}."""
        import time
        T = min(len(self.demand), t + 1 + self.horizon)
        m = self._model(T)
        lo, hi = m["lo"].copy(), m["hi"].copy()
        lo[m["demand_rows"]] = hi[m["demand_rows"]] = self.demand[:T]
        lo[m["reserve_rows"]] = self.demand[:T] + self.reserve[:T]
        lower, upper = np.zeros_like(m["upper"]), m["upper"].copy()
        for s, row in enumerate(history):                   # pin u for the hours already decided
            for i, u in enumerate(row):
                lower[i * T + s] = upper[i * T + s] = u
        for (i, s), u in pins.items():
            lower[i * T + s] = upper[i * T + s] = u
        start = time.perf_counter()
        res = milp(m["cost"], constraints=LinearConstraint(m["A"], lo, hi),
                   integrality=m["integrality"], bounds=Bounds(lower, upper))
        self.seconds += time.perf_counter() - start
        self.solves += 1
        return res.fun if res.status == 0 else np.inf

    def score(self, history, choice):
        """Cost of hours 0..t (history + choice at hour t, all fixed) plus the best next H hours.

        Returns inf if the fixed hours break a rule or no valid continuation exists.
        """
        t = len(history)
        return self._solve(history, t, {(i, t): int(u) for i, u in enumerate(choice)})

    def plant_values(self, history):
        """Look-ahead value of each plant at hour t = len(history): best score with it on minus off.

        The other plants stay free at hour t. Used to replace the one-hour cost c_i in the QUBO, so
        QAOA's samples lean toward choices that pay off over the next H hours. 2n MILP solves.
        +inf (cannot be on) / -inf (cannot be off) are returned as they are; the caller clips them.
        """
        t = len(history)
        values = np.zeros(self.n)
        for i in range(self.n):
            on, off = (self._solve(history, t, {(i, t): u}) for u in (1, 0))
            values[i] = 0.0 if not (np.isfinite(on) or np.isfinite(off)) else on - off
        return values

    def best(self, history, candidates):
        """The candidate with the lowest look-ahead score, and its score (None, inf if all dead ends)."""
        scores = [self.score(history, c) for c in candidates]
        k = int(np.argmin(scores))
        return (candidates[k], scores[k]) if np.isfinite(scores[k]) else (None, np.inf)

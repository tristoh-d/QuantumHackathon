"""Solve a src.hard_instances.Instance as a MILP with HiGHS (scipy.optimize.milp, the solver src/check.py uses).

Reports what branch and bound needed: wall time, nodes, the final optimality gap and whether it hit the time limit.
"""
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp


def solve(inst, time_limit=60.0):
    start = time.perf_counter()
    res = milp(inst.c, constraints=LinearConstraint(inst.A, inst.lo, inst.hi), integrality=inst.integrality,
               bounds=Bounds(0, inst.upper), options={"time_limit": time_limit, "disp": False})
    seconds = time.perf_counter() - start
    x = None if res.x is None else np.round(res.x[:inst.n]).astype(int)
    return dict(
        cost=None if res.x is None else float(res.fun),
        x=x,
        seconds=seconds,
        nodes=int(getattr(res, "mip_node_count", 0) or 0),
        gap=getattr(res, "mip_gap", None),
        timeout=res.status == 1,          # 1 = iteration or time limit reached
        status=int(res.status),
        message=res.message,
    )

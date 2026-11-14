"""Classical side: the exact MILP baseline (provided) and the cheapest-first rule (TODO 1)."""
import numpy as np

from src.check import check_schedule, solve_milp
from src.config import Problem, load_problem


# ---------------------------------------------------------------- TODO 1
def cheapest_first(plants, demand, reserve):
    """The cheapest-first rule a person might use. Returns a (hours x plants) 0/1 array.

    Rank plants by cost per MWh at full output, then each hour switch plants on down
    the list until capacity covers demand + reserve.

    - Cost per MWh at full output = marginal_cost_per_mwh + no_load_cost_per_h / pmax_mw.
    - np.argsort(values) gives plant indices from cheapest to most expensive.
    - For each hour t, add plants in that order until the sum of their pmax_mw is at
      least demand[t] + reserve[t].

    The rule ignores startup costs and min up/down times. Look at what that costs,
    and which rules it breaks.
    """
    schedule = np.zeros((len(demand), len(plants)), dtype=int)
    # TODO 1: rank the plants, then fill each hour (see the hints above).
    # When your lines are in, delete the raise line below.
    raise NotImplementedError("TODO 1: write the cheapest-first rule")
    return schedule


# ---------------------------------------------------------------- provided
def run_milp(problem: Problem, ramps: bool = False) -> dict:
    """Solve the exact MILP baseline. Returns cost, schedule, dispatch and solve seconds."""
    cost, schedule, dispatch, seconds = solve_milp(problem.plants, problem.demand, problem.reserve,
                                                   ramps=ramps)
    return dict(cost=cost, schedule=schedule, dispatch=dispatch, seconds=seconds)


def run_rule(problem: Problem, milp_cost=None, verbose=False) -> dict:
    """Run cheapest_first and score it with the checker."""
    schedule = cheapest_first(problem.plants, problem.demand, problem.reserve)
    result = check_schedule(problem.plants, problem.demand, problem.reserve, schedule,
                            milp_cost=milp_cost, verbose=verbose)
    result["schedule"] = np.asarray(schedule)
    return result


def run_classical(fleet: str = "5") -> dict:
    """MILP + cheapest-first rule for one fleet (the rule is None until TODO 1 is done)."""
    problem = load_problem(fleet)
    milp = run_milp(problem)
    try:
        rule = run_rule(problem, milp_cost=milp["cost"])
    except NotImplementedError:
        rule = None
    return dict(milp=milp, rule=rule)

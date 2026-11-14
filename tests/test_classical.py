"""TODO 1 acceptance tests: the cheapest-first rule. Skipped until TODO 1 is filled in."""
import numpy as np

from src.check import check_schedule
from src.classical import cheapest_first
from tests.conftest import call_or_skip


def test_shape_and_binary(problem):
    s = np.asarray(call_or_skip(cheapest_first, problem.plants, problem.demand, problem.reserve))
    assert s.shape == (24, problem.n)
    assert set(np.unique(s)) <= {0, 1}


def test_reserve_met_every_hour(problem):
    s = np.asarray(call_or_skip(cheapest_first, problem.plants, problem.demand, problem.reserve))
    pmax = np.array([p["pmax_mw"] for p in problem.plants])
    assert np.all(s @ pmax >= problem.demand + problem.reserve)


def test_each_hour_is_a_prefix_of_one_ranking(problem):
    """Every hour switches on the first k plants of the same ranking, and stops as soon as capacity is enough."""
    s = np.asarray(call_or_skip(cheapest_first, problem.plants, problem.demand, problem.reserve))
    pmax = np.array([p["pmax_mw"] for p in problem.plants])
    order = np.argsort([p["marginal_cost_per_mwh"] + p["no_load_cost_per_h"] / p["pmax_mw"] for p in problem.plants])
    for t, row in enumerate(s):
        k = int(row.sum())
        assert set(np.flatnonzero(row)) == set(order[:k]), f"hour {t} is not a prefix of the ranking"
        if k > 1:
            assert pmax[order[:k - 1]].sum() < problem.demand[t] + problem.reserve[t], f"hour {t} added one too many"


def test_not_cheaper_than_milp(problem, milp):
    s = call_or_skip(cheapest_first, problem.plants, problem.demand, problem.reserve)
    r = check_schedule(problem.plants, problem.demand, problem.reserve, s, milp_cost=milp["cost"], verbose=False)
    assert r["total_cost"] >= milp["cost"] - 1e-6


def test_works_on_10_plants(problem10):
    s = np.asarray(call_or_skip(cheapest_first, problem10.plants, problem10.demand, problem10.reserve))
    assert s.shape == (24, 10)

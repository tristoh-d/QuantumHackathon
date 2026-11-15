"""Classical look-ahead (src/lookahead.py) and the hybrid options of schedule_day."""
import numpy as np
import pytest

from src.check import check_schedule
from src.classical import run_milp
from src.config import load_problem
from src.lookahead import Lookahead
from src.scheduler import run_day


@pytest.fixture(scope="module")
def five():
    problem = load_problem("5")
    return problem, run_milp(problem)


def test_full_horizon_from_milp_hour0_is_milp_cost(five):
    """Pin hour 0 to the MILP's choice and look ahead over the rest of the day: the MILP optimum."""
    problem, milp = five
    la = Lookahead(problem.plants, problem.demand, problem.reserve, horizon=len(problem.demand))
    assert la.score([], milp["schedule"][0]) == pytest.approx(milp["cost"], rel=1e-6)


def test_fully_fixed_day_scores_like_the_checker(five):
    problem, milp = five
    sched = milp["schedule"]
    la = Lookahead(problem.plants, problem.demand, problem.reserve, horizon=0)
    checked = check_schedule(problem.plants, problem.demand, problem.reserve, sched, verbose=False)
    assert la.score(list(sched[:-1]), sched[-1]) == pytest.approx(checked["total_cost"], rel=1e-6)


def test_broken_min_up_is_a_dead_end(five):
    """The MILP starts GAS_CC at hour 5; turning it off at hour 6 breaks its 8 h min up time: score inf.
    The same hour with GAS_CC kept on is fine, and the replacement has enough capacity on its own."""
    problem, milp = five
    sched = [list(r) for r in milp["schedule"]]
    assert sched[4][1] == 0 and sched[5][1] == 1 and sched[6][1] == 1
    la = Lookahead(problem.plants, problem.demand, problem.reserve, horizon=2)
    assert np.isfinite(la.score(sched[:6], sched[6]))
    assert np.isinf(la.score(sched[:6], [1, 0, 1, 1, 1]))


def test_lookahead_zero_is_the_old_loop(five):
    problem, milp = five
    a = run_day(problem, milp["cost"], sampler="random", shots=200, seed=7, verbose=False)
    b = run_day(problem, milp["cost"], sampler="random", shots=200, seed=7, lookahead=0, verbose=False)
    assert np.array_equal(a["schedule"], b["schedule"])


def test_all_choices_with_lookahead_reach_the_optimum(five):
    """With every choice proposed and 4 h of look-ahead, the 5-plant day is solved exactly."""
    problem, milp = five
    r = run_day(problem, milp["cost"], sampler="all", lookahead=4, verbose=False)
    assert r["valid"] and abs(r["gap_pct"]) < 1e-6


def test_lookahead_beats_hour_by_hour(five):
    problem, milp = five
    greedy = run_day(problem, milp["cost"], sampler="random", shots=200, seed=7, verbose=False)
    ahead = run_day(problem, milp["cost"], sampler="random", shots=200, seed=7, lookahead=1, verbose=False)
    assert ahead["valid"] and ahead["total_cost"] < greedy["total_cost"]


@pytest.mark.slow
def test_shaped_qubo_day_is_valid(five):
    pytest.importorskip("qiskit")
    problem, milp = five
    r = run_day(problem, milp["cost"], sampler="qaoa", shots=50, seed=0, lookahead=4, shape_qubo=True,
                verbose=False)
    assert r["valid"] and r["gap_pct"] < 7.06

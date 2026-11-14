"""The provided pieces: data, checker and MILP baseline. These should pass from the start."""
import numpy as np

from src.check import check_hour, check_schedule, hour_ok, locks


def test_data_shapes(problem, problem10):
    assert problem.n == 5 and problem10.n == 10
    assert len(problem.demand) == len(problem.reserve) == 24
    assert problem.names == ["COAL", "GAS_CC", "PEAKER_A", "PEAKER_B", "OIL"]
    assert problem.start_state == [1, 0, 0, 0, 0]


def test_capacity_is_in_50mw_blocks(problem, problem10):
    for p in problem10.plants:
        assert p["pmax_mw"] % 50 == 0


def test_milp_is_valid(problem, milp):
    r = check_schedule(problem.plants, problem.demand, problem.reserve, milp["schedule"],
                       milp_cost=milp["cost"], verbose=False)
    assert r["valid"], r["violations"]
    assert abs(r["gap_pct"]) < 1e-3
    assert milp["schedule"].shape == (24, 5)


def test_milp_10_plants_solves(problem10):
    from src.classical import run_milp
    m = run_milp(problem10)
    r = check_schedule(problem10.plants, problem10.demand, problem10.reserve, m["schedule"], verbose=False)
    assert r["valid"], r["violations"]


def test_all_on_is_more_expensive(problem, milp):
    r = check_schedule(problem.plants, problem.demand, problem.reserve, np.ones((24, 5)),
                       milp_cost=milp["cost"], verbose=False)
    assert r["gap_pct"] > 0


def test_coal_only_breaks_reserve_at_peak(problem):
    assert not hour_ok(problem.plants, problem.demand[15], problem.reserve[15], [1, 0, 0, 0, 0])


def test_locks_after_start(problem):
    must_on, must_off = locks(problem.plants, [[1, 1, 0, 0, 0]])     # GAS_CC just started
    assert 1 in must_on and must_off == []


def test_check_hour_reports_best(problem, milp):
    r = check_hour(problem.plants, problem.demand[12], problem.reserve[12], milp["schedule"][12],
                   was_on=milp["schedule"][11], verbose=False)
    assert r["best_choice"] is not None and r["valid"]

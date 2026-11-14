"""TVA fleet (data/plants_tva.csv) and TVA demand days (src/demand.py). All offline."""
import csv
import math
import socket
from dataclasses import replace

import numpy as np
import pytest

from src.check import check_schedule, hour_cost, load_demand, load_plants
from src.classical import run_milp
from src.config import BLOCK_MW, DATA_DIR, load_problem, tva_day_names, tva_meta
from src import demand as tva
from src.qubo import blocks_needed, capacity_weights


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Offline guarantee: any attempt to open a connection fails the test."""
    def refuse(*args, **kwargs):
        raise AssertionError("TVA tests must not use the network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(scope="module")
def plants():
    return load_plants(DATA_DIR / "plants_tva.csv")


# ---------------------------------------------------------------- schema
def test_plants_schema(plants):
    with open(DATA_DIR / "plants.csv") as f:
        expected = next(csv.reader(f))
    with open(DATA_DIR / "plants_tva.csv") as f:
        assert next(csv.reader(f)) == expected
    assert len(plants) == 20
    for p in plants:
        for k, v in p.items():
            if isinstance(v, float):
                assert not math.isnan(v), (p["plant_id"], k)
        assert 0 < p["pmin_mw"] <= p["pmax_mw"], p["plant_id"]
        assert p["marginal_cost_per_mwh"] > 0 and p["no_load_cost_per_h"] >= 0 and p["startup_cost"] > 0
        assert p["on_at_start"] == (0 if p["plant_id"].endswith("_CT") else 1)


def test_no_nuclear_or_hydro_rows(plants):
    names = {p["plant_id"] for p in plants}
    assert not any(n.endswith(("_NUC", "_PS")) or "HYDRO" in n for n in names)


def test_meta_matches_plants(plants):
    meta = tva_meta()["plants"]
    assert meta["n_plants"] == len(plants)
    assert meta["capacity_mw"] == sum(p["pmax_mw"] for p in plants)


# ---------------------------------------------------------------- feasibility
def test_saved_days_fit_the_fleet(plants):
    cap = sum(p["pmax_mw"] for p in plants)
    names = tva_day_names()
    assert len(names) == 8 * 5 + 2
    for name in names:
        demand, reserve = load_demand(DATA_DIR / "demand_tva" / f"{name}.csv")
        assert len(demand) == 24
        assert (demand + reserve).max() <= cap, name
        assert np.all(demand > 0)


def test_generated_days_fit_the_fleet(plants):
    cap = sum(p["pmax_mw"] for p in plants)
    for day in tva.sample_days(n=50, seed=1):
        assert tva.feasible(day, cap)
        assert np.array_equal(day.reserve, np.round(0.10 * day.demand))


def test_pool_drops_infeasible_days():
    stats = tva.pool_stats()
    assert stats["days_feasible"] + stats["days_infeasible"] == stats["days_total"]
    assert all(n > 0 for n in stats["per_stratum"].values())
    assert tva_meta()["pool"]["days_feasible"] == stats["days_feasible"]


# ---------------------------------------------------------------- determinism
def test_same_seed_same_days():
    a = tva.sample_days("summer", "weekday", n=10, seed=3)
    b = tva.sample_days("summer", "weekday", n=10, seed=3)
    assert [d.date for d in a] == [d.date for d in b]


def test_different_seeds_differ():
    a = tva.sample_days(n=10, seed=3)
    b = tva.sample_days(n=10, seed=4)
    assert [d.date for d in a] != [d.date for d in b]


@pytest.mark.parametrize("season", tva.SEASON_ORDER)
@pytest.mark.parametrize("daytype", tva.DAYTYPES)
def test_strata_filters(season, daytype):
    for d in tva.sample_days(season, daytype, n=5, seed=0):
        assert (d.season, d.daytype) == (season, daytype)
        month, weekday = int(d.date[5:7]), np.datetime64(d.date).astype("datetime64[D]").item().weekday()
        assert tva.SEASON_ORDER[(month % 12) // 3] == season
        assert (weekday >= 5) == (daytype == "weekend")


def test_without_replacement_is_distinct():
    days = tva.sample_days("fall", "weekend", n=20, seed=0, replace=False)
    assert len({d.date for d in days}) == 20


def test_bad_stratum_rejected():
    with pytest.raises(ValueError):
        tva.sample_days("monsoon")


def test_scale_to():
    day = tva.sample_days(n=1, seed=0, scale_to=850)[0]
    assert (day.demand + day.reserve).max() <= 850 * 1.01


# ---------------------------------------------------------------- loader + MILP
@pytest.mark.parametrize("day", ["peak", "min", "summer_weekday_0", "sample:winter:weekend:4"])
def test_milp_solves_tva_days(day):
    problem = load_problem("tva", day=day)
    assert problem.n == 20 and len(problem.demand) == 24
    milp = run_milp(problem)
    result = check_schedule(problem.plants, problem.demand, problem.reserve, milp["schedule"], verbose=False)
    assert result["violations"] == []
    assert result["total_cost"] == pytest.approx(milp["cost"], rel=1e-6)


def test_load_problem_by_date():
    date = tva.extreme_days()["peak"].date
    a, b = load_problem("tva", day=date), load_problem("tva", day="peak")
    assert np.array_equal(a.demand, b.demand)


def test_day_only_for_tva():
    with pytest.raises(ValueError):
        load_problem("5", day="peak")


# ---------------------------------------------------------------- QAOA blocks
def test_block_autopick(plants):
    meta = tva_meta()["plants"]
    blocks, n_slack = tva.block_layout([p["pmax_mw"] for p in plants], meta["block_mw"])
    assert n_slack == meta["n_slack"]
    assert len(plants) + n_slack == meta["n_qubits"] <= meta["max_sim_qubits"]
    assert min(blocks) >= 1


def test_block_layout_matches_5_plant_default(problem):
    _, n_slack = tva.block_layout([p["pmax_mw"] for p in problem.plants], BLOCK_MW)
    assert n_slack == 3


def test_block_view_keeps_dollars(problem):
    # A 5-plant problem with pmax already whole 100 MW blocks: the view must give identical costs.
    plants = [dict(p, pmax_mw=max(100, round(p["pmax_mw"] / 100) * 100)) for p in problem.plants]
    real = replace(problem, plants=plants, block_mw=100)
    view = real.block_view()
    assert view.block_mw == BLOCK_MW
    on, was_on = [1, 1, 0, 1, 0], [1, 0, 0, 0, 0]
    for t in (0, 12):
        assert hour_cost(view.plants, view.demand[t], on, was_on) == pytest.approx(
            hour_cost(real.plants, real.demand[t], on, was_on))
        assert blocks_needed(view.demand[t], view.reserve[t]) == math.ceil(
            (real.demand[t] + real.reserve[t]) / 100 - 1e-9)
    assert list(capacity_weights(view.plants, 0)) == [p["pmax_mw"] / 100 for p in plants]

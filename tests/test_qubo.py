"""TODO 2 and TODO 3 acceptance tests. Skipped until those TODOs are filled in.

The QUBO is checked against the energy formula written out directly (no matrix):
    E(x, s) = sum_i c_i x_i + A * (sum_i a_i x_i - (s_0 + 2 s_1 + 4 s_2) - r)^2
so a correct (Q, offset) must reproduce it on every bitstring.
"""
import numpy as np
import pytest

from src.check import check_hour
from src.config import N_SLACK
from src.qubo import (all_energies, blocks_needed, brute_force_qubo, build_qubo, capacity_weights, index_bits,
                      plant_hour_costs)
from tests.conftest import call_or_skip

# ---------------------------------------------------------------- TODO 2


def test_costs_shape(problem):
    c = call_or_skip(plant_hour_costs, problem.plants, problem.start_state)
    assert np.shape(c) == (problem.n,)


def test_startup_only_charged_when_off(problem):
    off = call_or_skip(plant_hour_costs, problem.plants, [0] * problem.n)
    on = call_or_skip(plant_hour_costs, problem.plants, [1] * problem.n)
    np.testing.assert_allclose(off - on, [p["startup_cost"] for p in problem.plants])


def test_cheapest_plant_already_on_pays_only_no_load(problem):
    c = call_or_skip(plant_hour_costs, problem.plants, [1] * problem.n)
    i = int(np.argmin([p["marginal_cost_per_mwh"] for p in problem.plants]))
    assert c[i] == pytest.approx(problem.plants[i]["no_load_cost_per_h"])


def test_costs_are_positive(problem10):
    c = call_or_skip(plant_hour_costs, problem10.plants, [1] * problem10.n)
    assert np.all(c > 0)


# ---------------------------------------------------------------- TODO 3


def direct_energy(plants, demand_mw, reserve_mw, was_on, y, penalty=None, n_slack=N_SLACK):
    c = plant_hour_costs(plants, was_on)
    A = 2 * c.max() if penalty is None else penalty
    b, r = capacity_weights(plants, n_slack), blocks_needed(demand_mw, reserve_mw)
    return c @ y[:len(plants)] + A * (b @ y - r) ** 2


@pytest.mark.parametrize("hour", [0, 7, 12, 15, 21])
@pytest.mark.parametrize("was_on", [[1, 0, 0, 0, 0], [1, 1, 0, 0, 0], [1, 1, 1, 1, 1]])
def test_qubo_matches_formula_on_every_bitstring(problem, hour, was_on):
    Q, offset = call_or_skip(build_qubo, problem.plants, problem.demand[hour], problem.reserve[hour], was_on)
    assert Q.shape == (problem.n + N_SLACK,) * 2
    bits = index_bits(len(Q))
    expected = np.array([direct_energy(problem.plants, problem.demand[hour], problem.reserve[hour], was_on, y)
                         for y in bits])
    np.testing.assert_allclose(all_energies(Q, offset), expected, rtol=1e-9, atol=1e-6)


def test_qubo_uses_upper_triangle_only(problem):
    Q, _ = call_or_skip(build_qubo, problem.plants, problem.demand[12], problem.reserve[12], problem.start_state)
    assert np.allclose(np.tril(Q, -1), 0), "pair terms belong at Q[j, k] with j < k"


def test_penalty_argument_is_used(problem):
    Q1, o1 = call_or_skip(build_qubo, problem.plants, problem.demand[12], problem.reserve[12], problem.start_state,
                          penalty=1000.0)
    Q2, o2 = build_qubo(problem.plants, problem.demand[12], problem.reserve[12], problem.start_state, penalty=2000.0)
    assert not np.allclose(Q1, Q2) or o1 != o2


def test_milestone3_match_at_hour_12(problem, milp):
    """Milestone 3 is done when the brute-forced QUBO prints 'Match!' for TEST_HOUR = 12."""
    t = 12
    was_on = milp["schedule"][t - 1]
    Q, offset = call_or_skip(build_qubo, problem.plants, problem.demand[t], problem.reserve[t], was_on)
    bits, _ = brute_force_qubo(Q, offset)
    r = check_hour(problem.plants, problem.demand[t], problem.reserve[t], bits[:problem.n], was_on=was_on,
                   verbose=False)
    assert r["matches_best"]


def test_qubo_10_plants_builds(problem10):
    # Stretch goal: how many slack bits does the 10-plant fleet need? Pass n_slack= to build_qubo.
    Q, _ = call_or_skip(build_qubo, problem10.plants, problem10.demand[12], problem10.reserve[12],
                        problem10.start_state)
    assert Q.shape == (10 + N_SLACK,) * 2

"""The Max-Cut primer. Brute force passes now; the QAOA tests skip until the primer TODOs are done."""
import pytest

from src.maxcut import EDGES_LARGE, EDGES_SMALL, N_LARGE, N_SMALL, brute_force, cut_value, qaoa_circuit
from tests.conftest import call_or_skip


def test_cut_value():
    assert cut_value("000000", EDGES_SMALL) == 0
    assert cut_value("010101", EDGES_SMALL) == 7      # the 2 x 3 grid is bipartite: every line can be cut


def test_brute_force():
    assert brute_force(N_SMALL, EDGES_SMALL)[0] == len(EDGES_SMALL)
    assert brute_force(N_LARGE, EDGES_LARGE)[0] == len(EDGES_LARGE)


def test_cost_layer_has_two_cx_per_edge():
    pytest.importorskip("qiskit")
    qc = call_or_skip(qaoa_circuit, [0.3, 0.2], N_SMALL, EDGES_SMALL, 1)
    assert qc.count_ops().get("cx", 0) == 2 * len(EDGES_SMALL)

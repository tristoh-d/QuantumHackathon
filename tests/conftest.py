"""Shared fixtures. Tests for unfinished TODOs SKIP (with the TODO named) instead of failing."""
import pytest

from src.classical import run_milp
from src.config import load_problem


def call_or_skip(fn, *args, **kwargs):
    """Call fn; if a TODO inside it still raises NotImplementedError, skip the test with that message."""
    try:
        return fn(*args, **kwargs)
    except NotImplementedError as e:
        pytest.skip(f"not implemented yet: {e}")


@pytest.fixture(scope="session")
def problem():
    return load_problem("5")


@pytest.fixture(scope="session")
def problem10():
    return load_problem("10")


@pytest.fixture(scope="session")
def milp(problem):
    return run_milp(problem)

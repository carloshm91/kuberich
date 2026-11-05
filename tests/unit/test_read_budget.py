"""A read charge cannot exceed its finite shared logical-call bound."""

import pytest

from kuberich.domain.read_budget import ReadBudget, ReadBudgetExceeded
from kuberich.errors import AppError

pytestmark = pytest.mark.fast


@pytest.mark.parametrize("maximum", [0, -1, True, 65, 1.5, "1", None])
def test_invalid_budget_fails_before_use(maximum):
    with pytest.raises(AppError):
        ReadBudget(maximum)


def test_default_budget_and_exact_exhaustion_are_deterministic():
    budget = ReadBudget()
    assert budget.used == 0
    for expected in range(1, 65):
        budget.charge()
        assert budget.used == expected
    for _ in range(2):
        with pytest.raises(ReadBudgetExceeded):
            budget.charge()
        assert budget.used == 64
    with pytest.raises(AttributeError):
        budget.used = 0


def test_smaller_shared_budget_is_not_replenished():
    budget = ReadBudget(1)
    budget.charge()
    with pytest.raises(ReadBudgetExceeded):
        budget.charge()
    assert budget.used == 1

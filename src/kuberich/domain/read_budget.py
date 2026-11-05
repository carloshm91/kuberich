"""Deterministic shared bound on logical Reader transport calls."""

from kuberich.errors import AppError


class ReadBudgetExceeded(Exception):
    """No further logical Reader transport call is permitted."""


class ReadBudget:
    def __init__(self, max_requests: int = 64) -> None:
        if type(max_requests) is not int or not 1 <= max_requests <= 64:
            raise AppError("Read budget must be an integer from 1 through 64.")
        self._maximum = max_requests
        self._used = 0

    @property
    def used(self) -> int:
        return self._used

    def charge(self) -> None:
        if self._used >= self._maximum:
            raise ReadBudgetExceeded
        self._used += 1

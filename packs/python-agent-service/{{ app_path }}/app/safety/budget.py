"""A per-user budget, in memory: requests and model tokens in a fixed window.

It stops one user from spending without limit. It is per process: a service with several replicas gives each
its own budget, so put a shared store behind `UserBudget` before relying on a global limit.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

_PRUNE_ABOVE = 1024


class BudgetExceededError(Exception):
    def __init__(self, reason: str, retry_after_seconds: int) -> None:
        super().__init__(f"The {reason} budget is used up")
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds


@dataclass
class _Window:
    started: float
    requests: int = 0
    tokens: int = 0


class UserBudget:
    def __init__(
        self,
        *,
        max_requests: int,
        max_tokens: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_requests = max_requests
        self._max_tokens = max_tokens
        self._window = window_seconds
        self._clock = clock
        self._windows: dict[str, _Window] = {}

    def reserve(self, user_id: str) -> None:
        """Count one request for the user, or raise `BudgetExceededError` when the window's budget is used up."""

        now = self._clock()
        window = self._current(user_id, now)
        retry_after = max(1, int(window.started + self._window - now) + 1)
        if window.requests >= self._max_requests:
            raise BudgetExceededError("request", retry_after)
        if window.tokens >= self._max_tokens:
            raise BudgetExceededError("token", retry_after)
        window.requests += 1

    def record_tokens(self, user_id: str, tokens: int) -> None:
        """Add the tokens a finished turn used. The next request is refused once the total reaches the limit."""

        self._current(user_id, self._clock()).tokens += max(0, tokens)

    def _current(self, user_id: str, now: float) -> _Window:
        window = self._windows.get(user_id)
        if window is None or now - window.started >= self._window:
            if len(self._windows) > _PRUNE_ABOVE:
                self._windows = {key: item for key, item in self._windows.items() if now - item.started < self._window}
            window = self._windows[user_id] = _Window(started=now)
        return window

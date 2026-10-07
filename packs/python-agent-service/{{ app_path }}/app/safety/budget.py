"""A per-user budget, in memory: requests, concurrent turns and model tokens in a fixed window.

It stops one user from spending without limit, including by sending many turns at once:
- a turn takes one of the user's few concurrent slots, so only a few turns of one user run at a time;
- before each model call the turn reserves the most that call can cost, and the call is refused when the
  tokens used, plus the tokens reserved by calls in flight, plus this reservation, would pass the window's limit;
- when a call completes its real usage replaces the reservation, so a turn that fails later still pays for the
  calls it completed.

It is per process: a service with several replicas gives each its own budget, so put a shared store behind
`UserBudget` before relying on a global limit.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

_PRUNE_ABOVE = 1024
CONCURRENT = "concurrent request"


class BudgetExceededError(Exception):
    def __init__(self, reason: str, retry_after_seconds: int) -> None:
        super().__init__(f"The {reason} budget is used up")
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds


@dataclass
class _Account:
    started: float
    requests: int = 0
    tokens: int = 0
    reserved: int = 0
    active: int = 0


class UserBudget:
    def __init__(
        self,
        *,
        max_requests: int,
        max_tokens: int,
        window_seconds: float,
        max_concurrent_turns: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_requests = max_requests
        self._max_tokens = max_tokens
        self._window = window_seconds
        self._max_concurrent = max_concurrent_turns
        self._clock = clock
        self._accounts: dict[str, _Account] = {}
        self._lock = threading.Lock()

    def begin_turn(self, user_id: str) -> TurnBudget:
        """Count one request and take a concurrent slot, or raise `BudgetExceededError` when the window's budget is used up.

        The caller must `finish()` the returned turn (it is a context manager).
        """

        with self._lock:
            now = self._clock()
            account = self._account(user_id, now)
            retry_after = max(1, int(account.started + self._window - now) + 1)
            if account.requests >= self._max_requests:
                raise BudgetExceededError("request", retry_after)
            if account.tokens + account.reserved >= self._max_tokens:
                raise BudgetExceededError("token", retry_after)
            if account.active >= self._max_concurrent:
                raise BudgetExceededError(CONCURRENT, 1)
            account.requests += 1
            account.active += 1
        return TurnBudget(self, user_id)

    # --- called by `TurnBudget` and `CallReservation` ----------------------------------------------------------

    def tokens_used(self, user_id: str) -> int:
        """The tokens the user's completed model calls have used in the current window (not what is reserved)."""

        with self._lock:
            account = self._accounts.get(user_id)
            if account is None or self._clock() - account.started >= self._window:
                return 0
            return account.tokens

    def _reserve(self, user_id: str, tokens: int) -> None:
        with self._lock:
            now = self._clock()
            account = self._account(user_id, now)
            if account.tokens + account.reserved + tokens > self._max_tokens:
                raise BudgetExceededError("token", max(1, int(account.started + self._window - now) + 1))
            account.reserved += tokens

    def _settle(self, user_id: str, reserved: int, used: int) -> None:
        with self._lock:
            account = self._account(user_id, self._clock())
            account.reserved = max(0, account.reserved - reserved)
            account.tokens += max(0, used)

    def _finish(self, user_id: str) -> None:
        with self._lock:
            account = self._account(user_id, self._clock())
            account.active = max(0, account.active - 1)

    def _account(self, user_id: str, now: float) -> _Account:
        account = self._accounts.get(user_id)
        if account is None or (now - account.started >= self._window and account.active == 0 and account.reserved == 0):
            if len(self._accounts) > _PRUNE_ABOVE:
                self._accounts = {
                    key: item
                    for key, item in self._accounts.items()
                    if item.active or item.reserved or now - item.started < self._window
                }
            account = self._accounts[user_id] = _Account(started=now)
        elif now - account.started >= self._window:
            # The window renewed while a turn was running: its counters start again, what is in flight stays counted.
            account.started = now
            account.requests = 0
            account.tokens = 0
        return account


class CallReservation:
    """The capacity one model call may use. Settle it with the call's real usage, or cancel it when the call failed."""

    def __init__(self, budget: UserBudget, user_id: str, tokens: int) -> None:
        self._budget = budget
        self._user_id = user_id
        self._tokens = tokens
        self._closed = False

    def settle(self, used: int) -> None:
        """The call completed: its usage replaces the reservation."""

        if not self._closed:
            self._closed = True
            self._budget._settle(self._user_id, self._tokens, used)

    def cancel(self) -> None:
        """The call failed before it returned any usage: the reservation is released and nothing is charged."""

        self.settle(0)


class TurnBudget:
    """One turn's hold on its user's budget: reserve capacity before each model call, and finish when the turn ends."""

    def __init__(self, budget: UserBudget, user_id: str) -> None:
        self._budget = budget
        self._user_id = user_id
        self._finished = False

    def reserve_call(self, tokens: int) -> CallReservation:
        """Reserve the most the next model call can cost, or raise `BudgetExceededError` when the window cannot hold it."""

        self._budget._reserve(self._user_id, max(1, tokens))
        return CallReservation(self._budget, self._user_id, max(1, tokens))

    def finish(self) -> None:
        if not self._finished:
            self._finished = True
            self._budget._finish(self._user_id)

    def __enter__(self) -> TurnBudget:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.finish()


def unlimited_turn() -> TurnBudget:
    """A turn with no limit, for the evaluation run and for tests, where no user's spending is being protected."""

    return UserBudget(
        max_requests=10**9, max_tokens=10**12, window_seconds=3600, max_concurrent_turns=10**9
    ).begin_turn("evaluation")

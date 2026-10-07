from __future__ import annotations

import os

import pytest

from tests.support import SigningKey, make_signing_key


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's own AGENT_* or ANTHROPIC_* variables never change what a test sees."""

    for name in list(os.environ):
        if name.startswith("AGENT_") or name.startswith("ANTHROPIC_"):
            monkeypatch.delenv(name)


@pytest.fixture(scope="session")
def signing_key() -> SigningKey:
    return make_signing_key("test-key-1")


@pytest.fixture(scope="session")
def other_key() -> SigningKey:
    return make_signing_key("other-key")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"

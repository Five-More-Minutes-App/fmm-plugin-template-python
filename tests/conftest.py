from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest_asyncio

from fmm_client import FiveMoreMinutes

from .mock_fmm import KEY, MockFmm


@pytest_asyncio.fixture
async def make() -> AsyncIterator[Callable[..., Awaitable[tuple[MockFmm, FiveMoreMinutes]]]]:
    """Starts a mock service and a client for it. Everything is closed afterwards."""
    opened: list[tuple[MockFmm, FiveMoreMinutes]] = []

    async def factory(**options: Any) -> tuple[MockFmm, FiveMoreMinutes]:
        timeout = options.pop("timeout", 10.0)
        mock = MockFmm(**options)
        url = await mock.start()
        client = FiveMoreMinutes(url, KEY, timeout=timeout)
        opened.append((mock, client))
        return mock, client

    yield factory

    for mock, client in opened:
        await client.close()
        await mock.close()

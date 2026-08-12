import asyncio
from collections.abc import AsyncIterator

import pytest

from scam2market.resilience.batching import bounded_batches


@pytest.mark.asyncio
async def test_idle_flush_does_not_cancel_pending_source_read() -> None:
    async def delayed_source() -> AsyncIterator[int]:
        await asyncio.sleep(0.03)
        yield 1
        await asyncio.sleep(0.03)
        yield 2

    batches = [
        batch
        async for batch in bounded_batches(
            delayed_source(), max_batch_size=10, max_wait_seconds=0.01
        )
    ]
    assert batches == [[1], [2]]


@pytest.mark.asyncio
async def test_batch_size_flushes_without_waiting_for_deadline() -> None:
    async def source() -> AsyncIterator[int]:
        for value in range(5):
            yield value

    batches = [
        batch async for batch in bounded_batches(source(), max_batch_size=2, max_wait_seconds=1)
    ]
    assert batches == [[0, 1], [2, 3], [4]]

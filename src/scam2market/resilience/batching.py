import asyncio
from collections.abc import AsyncIterator
from time import monotonic


async def bounded_batches[T](
    source: AsyncIterator[T],
    *,
    max_batch_size: int,
    max_wait_seconds: float,
) -> AsyncIterator[list[T]]:
    """Apply bounded buffering so high-volume consumers cannot grow memory without limit."""
    if max_batch_size < 1 or max_wait_seconds <= 0:
        raise ValueError("batch limits must be positive")
    iterator = source.__aiter__()
    exhausted = False
    while not exhausted:
        batch: list[T] = []
        deadline = monotonic() + max_wait_seconds
        while len(batch) < max_batch_size:
            timeout = max(0.0, deadline - monotonic())
            try:
                item = await asyncio.wait_for(iterator.__anext__(), timeout=timeout)
            except TimeoutError:
                break
            except StopAsyncIteration:
                exhausted = True
                break
            batch.append(item)
        if batch:
            yield batch

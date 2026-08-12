import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
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
    pending: asyncio.Future[T] | None = None
    try:
        while not exhausted:
            batch: list[T] = []
            deadline = monotonic() + max_wait_seconds
            while len(batch) < max_batch_size:
                timeout = max(0.0, deadline - monotonic())
                if pending is None:
                    pending = asyncio.ensure_future(iterator.__anext__())
                done, _ = await asyncio.wait({pending}, timeout=timeout)
                if not done:
                    break
                try:
                    item = pending.result()
                except StopAsyncIteration:
                    exhausted = True
                    break
                finally:
                    pending = None
                batch.append(item)
            if batch:
                yield batch
    finally:
        if pending is not None:
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending

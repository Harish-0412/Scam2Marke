from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from scam2market.verification.schemas import DisclosureDocument


class DisclosureProvider(Protocol):
    name: str

    def documents(self) -> AsyncIterator[DisclosureDocument]: ...


class ReplayDisclosureProvider:
    name = "disclosure-replay-v1"

    def __init__(self, documents: Sequence[DisclosureDocument]) -> None:
        self._documents = sorted(
            documents, key=lambda item: (item.published_at, item.source_document_id)
        )

    async def documents(self) -> AsyncIterator[DisclosureDocument]:
        for document in self._documents:
            yield document

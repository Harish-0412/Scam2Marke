from collections.abc import AsyncIterator
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, Field, ValidationError

OTX_HOST = "otx.alienvault.com"
JsonObject = dict[str, Any]


class OTXRateLimited(RuntimeError):
    def __init__(self, retry_after: datetime | float | None) -> None:
        super().__init__("OTX rate limit exceeded")
        self.retry_after = retry_after


class OTXIndicator(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=64)
    indicator: str = Field(min_length=1, max_length=4096)
    created: datetime
    modified: datetime | None = None
    description: str = Field(default="", max_length=4000)


class OTXPulse(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    name: str = Field(default="", max_length=500)
    modified: datetime
    description: str = Field(default="", max_length=4000)
    tags: list[str] = Field(default_factory=list)
    TLP: str = Field(default="white", max_length=16)
    indicators: list[dict[str, Any]] = Field(default_factory=list)


class OTXPage(BaseModel):
    pulses: list[OTXPulse]
    next_url: str | None
    malformed_items: int
    byte_count: int


class OTXClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://otx.alienvault.com/api/v1/",
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or parsed.hostname != OTX_HOST:
            raise ValueError("OTX base URL must use the fixed HTTPS OTX host")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/") + "/"
        self._client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes

    async def fetch_page(
        self,
        *,
        page: int = 1,
        limit: int = 100,
        modified_since: datetime | None = None,
        url: str | None = None,
    ) -> OTXPage:
        target = url or urljoin(self._base_url, "pulses/subscribed")
        self._validate_target(target)
        params: dict[str, str | int] | None = None
        if url is None:
            params = {"page": page, "limit": limit}
            if modified_since is not None:
                params["modified_since"] = modified_since.isoformat()
        response = await self._client.get(
            target,
            params=params,
            headers={"X-OTX-API-KEY": self._api_key, "Accept": "application/json"},
        )
        if response.is_redirect:
            raise httpx.TooManyRedirects("OTX redirects are rejected to protect credentials")
        if response.status_code == 429:
            raise OTXRateLimited(_retry_after(response.headers.get("Retry-After")))
        response.raise_for_status()
        if len(response.content) > self._max_response_bytes:
            raise ValueError("OTX response exceeds configured byte limit")
        payload = _json_object(response.json())
        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            raise ValueError("OTX results must be a list")
        pulses: list[OTXPulse] = []
        malformed = 0
        for raw in raw_results:
            try:
                pulses.append(OTXPulse.model_validate(raw))
            except ValidationError:
                malformed += 1
        next_url = payload.get("next")
        if next_url is not None:
            if not isinstance(next_url, str):
                raise ValueError("OTX next cursor must be a URL")
            self._validate_target(next_url)
        return OTXPage(
            pulses=pulses,
            next_url=next_url,
            malformed_items=malformed,
            byte_count=len(response.content),
        )

    async def fetch_pulses(
        self,
        *,
        modified_since: datetime | None = None,
        page_size: int = 100,
        max_pages: int = 5,
        max_records: int = 1000,
    ) -> AsyncIterator[OTXPulse]:
        next_url: str | None = None
        emitted = 0
        for page_number in range(1, max_pages + 1):
            page = await self.fetch_page(
                page=page_number, limit=page_size, modified_since=modified_since, url=next_url
            )
            for pulse in page.pulses:
                if emitted >= max_records:
                    return
                emitted += 1
                yield pulse
            next_url = page.next_url
            if not next_url:
                return

    def _validate_target(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != OTX_HOST:
            raise ValueError("OTX request target must use the fixed HTTPS OTX host")

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _retry_after(value: str | None) -> datetime | float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return parsedate_to_datetime(value)


def _json_object(value: object) -> JsonObject:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("OTX response must be a JSON object with string keys")
    return {str(key): item for key, item in value.items()}

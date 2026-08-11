import base64
import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

OTX_DISCOVERY_URL = "https://otx.alienvault.com/taxii/discovery"
JsonObject = dict[str, Any]


class OTXClient:
    def __init__(self) -> None:
        api_key = os.getenv("OTX_API_KEY")
        if not api_key:
            raise RuntimeError("OTX_API_KEY environment variable not set")
        self.api_key = api_key
        token = base64.b64encode(f"{api_key}:".encode()).decode()
        self.headers: dict[str, str] = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
        }
        self.client = httpx.AsyncClient(headers=self.headers, timeout=30.0)

    async def discover(self) -> JsonObject:
        response = await self.client.get(OTX_DISCOVERY_URL)
        response.raise_for_status()
        return _json_object(response.json())

    async def get_collections(self, api_root: str) -> list[JsonObject]:
        response = await self.client.get(f"{api_root}/collections/")
        response.raise_for_status()
        payload = _json_object(response.json())
        collections = payload.get("collections")
        if not isinstance(collections, list):
            return []
        return [_json_object(item) for item in collections]

    async def get_objects(self, collection_url: str) -> AsyncIterator[JsonObject]:
        async with self.client.stream("GET", f"{collection_url}/objects/") as stream:
            stream.raise_for_status()
            async for line in stream.aiter_lines():
                if line:
                    yield _json_object(json.loads(line))

    async def fetch_pulses(self) -> AsyncIterator[JsonObject]:
        discovery = await self.discover()
        api_roots = discovery.get("api_roots")
        if not isinstance(api_roots, list) or not api_roots:
            return
        api_root = _json_object(api_roots[0]).get("url")
        if not isinstance(api_root, str):
            return
        collections = await self.get_collections(api_root)
        pulse_collection = next(
            (
                collection
                for collection in collections
                if "pulse" in str(collection.get("title", "")).lower()
            ),
            None,
        )
        if pulse_collection is None:
            return
        collection_url = pulse_collection.get("url")
        if not isinstance(collection_url, str):
            return
        async for item in self.get_objects(collection_url):
            yield item

    async def close(self) -> None:
        await self.client.aclose()


def _json_object(value: object) -> JsonObject:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("OTX response must be a JSON object with string keys")
    return {str(key): item for key, item in value.items()}

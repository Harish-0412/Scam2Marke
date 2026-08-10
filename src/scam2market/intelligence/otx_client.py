import os
import base64
import httpx
from typing import AsyncIterator, Dict, List

OTX_DISCOVERY_URL = "https://otx.alienvault.com/taxii/discovery"

class OTXClient:
    def __init__(self):
        self.api_key = os.getenv("OTX_API_KEY")
        if not self.api_key:
            raise RuntimeError("OTX_API_KEY environment variable not set")
        # Basic auth: username = API key, password empty
        token = base64.b64encode(f"{self.api_key}:".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        self.client = httpx.AsyncClient(headers=self.headers, timeout=30.0)

    async def discover(self) -> Dict:
        resp = await self.client.get(OTX_DISCOVERY_URL)
        resp.raise_for_status()
        return resp.json()

    async def get_collections(self, api_root: str) -> List[Dict]:
        url = f"{api_root}/collections/"
        resp = await self.client.get(url)
        resp.raise_for_status()
        return resp.json().get("collections", [])

    async def get_objects(self, collection_url: str) -> AsyncIterator[Dict]:
        # TAXII 2.1 get objects endpoint
        url = f"{collection_url}/objects/"
        async with self.client.stream("GET", url) as stream:
            async for line in stream.aiter_lines():
                if line:
                    yield httpx.Response(200, content=line).json()

    async def fetch_pulses(self) -> AsyncIterator[Dict]:
        # OTX publishes pulses under the collection "otx-pulses" (example).
        discovery = await self.discover()
        # Find the default API root (usually the first one)
        api_root = discovery.get("api_roots", [])[0].get("url")
        collections = await self.get_collections(api_root)
        pulses_coll = next((c for c in collections if "pulse" in c.get("title", "").lower()), None)
        if not pulses_coll:
            return
        collection_url = pulses_coll.get("url")
        async for obj in self.get_objects(collection_url):
            yield obj

    async def close(self):
        await self.client.aclose()

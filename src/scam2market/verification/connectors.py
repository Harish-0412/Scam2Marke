import hashlib
import html
import ipaddress
import json
import re
import socket
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

from scam2market.verification.schemas import DisclosureDocument

_TAG = re.compile(r"<[^>]+>")


class ConnectorError(RuntimeError):
    """A source connector failed in a way the worker can classify and persist."""

    def __init__(self, message: str, *, rate_limited: bool = False) -> None:
        super().__init__(message)
        self.rate_limited = rate_limited


class DisclosureConnector(Protocol):
    async def fetch(self, checkpoint: dict[str, Any] | None = None) -> "ConnectorBatch": ...


@dataclass(frozen=True)
class ConnectorBatch:
    documents: list[DisclosureDocument]
    checkpoint: dict[str, Any]
    source_watermark: datetime | None = None

    def __getitem__(self, index: int) -> DisclosureDocument:
        return self.documents[index]

    def __len__(self) -> int:
        return len(self.documents)


def stable_disclosure_id(policy_id: UUID, source_key: str, content_hash: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"official-disclosure:{policy_id}:{source_key}:{content_hash}")


class _HttpConnector:
    def __init__(
        self,
        *,
        policy_id: UUID,
        source_name: str,
        policy_version: str,
        trust_score: float,
        config: dict[str, Any],
        canonical_domains: list[str],
        client: httpx.AsyncClient,
        resolve_host: Callable[[str], list[str]],
        timeout_seconds: float = 15.0,
    ) -> None:
        self.policy_id = policy_id
        self.source_name = source_name
        self.policy_version = policy_version
        self.trust_score = trust_score
        self.config = config
        self.canonical_domains = {domain.lower().rstrip(".") for domain in canonical_domains}
        self.client = client
        self.resolve_host = resolve_host
        self.timeout = httpx.Timeout(timeout_seconds)

    async def fetch(self, checkpoint: dict[str, Any] | None = None) -> ConnectorBatch:
        raise NotImplementedError

    async def _get(self, url: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
        self._validate_url(url)
        try:
            response = await self.client.get(url, headers=headers, timeout=self.timeout)
            if response.status_code == 429:
                raise ConnectorError(f"source rate limited request to {url}", rate_limited=True)
            if response.status_code == 304:
                return response
            response.raise_for_status()
            return response
        except ConnectorError:
            raise
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise ConnectorError(f"source request failed for {url}: {exc}") from exc

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https":
            raise ConnectorError("connector URLs must use HTTPS")
        if not host or parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            raise ConnectorError("connector URL is not permitted")
        if host == "localhost" or host.endswith(".localhost"):
            raise ConnectorError("connector URL cannot target localhost")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ConnectorError("connector URL cannot target a non-public IP address")
        if host not in self.canonical_domains:
            raise ConnectorError(f"connector URL host is not canonical: {host}")
        try:
            resolved = self.resolve_host(host)
        except OSError as exc:
            raise ConnectorError(f"connector URL host could not be resolved: {host}") from exc
        if not resolved:
            raise ConnectorError(f"connector URL host did not resolve: {host}")
        for value in resolved:
            try:
                resolved_address = ipaddress.ip_address(value)
            except ValueError as exc:
                raise ConnectorError(f"connector URL resolved invalid address: {value}") from exc
            if not resolved_address.is_global:
                raise ConnectorError("connector URL resolved to a non-public IP address")

    @staticmethod
    def _conditional_headers(checkpoint: dict[str, Any] | None) -> dict[str, str]:
        checkpoint = checkpoint or {}
        headers: dict[str, str] = {}
        if checkpoint.get("etag"):
            headers["If-None-Match"] = str(checkpoint["etag"])
        if checkpoint.get("last_modified"):
            headers["If-Modified-Since"] = str(checkpoint["last_modified"])
        return headers

    @staticmethod
    def _response_checkpoint(
        checkpoint: dict[str, Any] | None, response: httpx.Response
    ) -> dict[str, Any]:
        result = dict(checkpoint or {})
        if response.headers.get("etag"):
            result["etag"] = response.headers["etag"]
        if response.headers.get("last-modified"):
            result["last_modified"] = response.headers["last-modified"]
        return result

    @staticmethod
    def _checkpoint_watermark(checkpoint: dict[str, Any] | None) -> datetime | None:
        value = (checkpoint or {}).get("source_watermark")
        return _parse_datetime(value, datetime.min.replace(tzinfo=UTC)) if value else None

    def _document(
        self,
        *,
        source_key: str,
        title: str,
        body: str,
        url: str | None,
        published_at: datetime,
        retrieved_at: datetime,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> DisclosureDocument:
        if url:
            self._validate_url(url)
        normalized_body = body.strip()
        content_hash = hashlib.sha256(normalized_body.encode()).hexdigest()
        return DisclosureDocument(
            disclosure_id=stable_disclosure_id(self.policy_id, source_key, content_hash),
            source=self.source_name,
            source_document_id=source_key,
            source_document_key=source_key,
            logical_source_key=str(self.config["logical_source_key"]),
            source_policy_id=self.policy_id,
            asset_id=self.config.get("asset_id"),
            title=title.strip() or "Untitled official disclosure",
            body=normalized_body,
            url=url,
            published_at=published_at,
            retrieved_at=retrieved_at,
            available_at=retrieved_at,
            source_policy_version=self.policy_version,
            reliability=self.trust_score,
            content_hash=content_hash,
            etag=etag,
            last_modified=last_modified,
        )


class OfficialFeedConnector(_HttpConnector):
    async def fetch(self, checkpoint: dict[str, Any] | None = None) -> ConnectorBatch:
        url = str(self.config.get("url") or "")
        if not url:
            raise ConnectorError("RSS/Atom connector requires connector_config.url")
        response = await self._get(url, headers=self._conditional_headers(checkpoint))
        response_checkpoint = self._response_checkpoint(checkpoint, response)
        if response.status_code == 304:
            return ConnectorBatch(
                [], response_checkpoint, self._checkpoint_watermark(response_checkpoint)
            )
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ConnectorError(f"invalid RSS/Atom XML: {exc}") from exc
        parsed_at = datetime.now(tz=UTC)
        entries = root.findall(".//item") or root.findall(".//{*}entry")
        documents: list[DisclosureDocument] = []
        for entry in entries:
            title = _xml_text(entry, "title") or "Untitled official disclosure"
            link = _entry_link(entry)
            source_key = (
                _xml_text(entry, "guid")
                or _xml_text(entry, "id")
                or link
                or hashlib.sha256(ET.tostring(entry)).hexdigest()
            )
            body = (
                _xml_text(entry, "description")
                or _xml_text(entry, "content")
                or _xml_text(entry, "summary")
                or title
            )
            published = _parse_datetime(
                _xml_text(entry, "pubDate")
                or _xml_text(entry, "published")
                or _xml_text(entry, "updated"),
                parsed_at,
            )
            documents.append(
                self._document(
                    source_key=source_key,
                    title=title,
                    body=html.unescape(_TAG.sub(" ", body)),
                    url=link,
                    published_at=published,
                    retrieved_at=parsed_at,
                    etag=response.headers.get("etag"),
                    last_modified=response.headers.get("last-modified"),
                )
            )
        retrieved = datetime.now(tz=UTC)
        documents = [
            item.model_copy(update={"retrieved_at": retrieved, "available_at": retrieved})
            for item in documents
        ]
        return ConnectorBatch(
            documents,
            response_checkpoint,
            max(
                (item.published_at for item in documents),
                default=self._checkpoint_watermark(response_checkpoint),
            ),
        )


class GitHubReleasesConnector(_HttpConnector):
    async def fetch(self, checkpoint: dict[str, Any] | None = None) -> ConnectorBatch:
        repository = str(self.config.get("repository") or "")
        url = str(
            self.config.get("url")
            or f"https://api.github.com/repos/{repository}/releases?per_page=100"
        )
        if not repository and "url" not in self.config:
            raise ConnectorError("GitHub connector requires connector_config.repository or url")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "Scam2Market/1.0"}
        headers.update(self._conditional_headers(checkpoint))
        if token := self.config.get("token"):
            headers["Authorization"] = f"Bearer {token}"
        response = await self._get(url, headers=headers)
        response_checkpoint = self._response_checkpoint(checkpoint, response)
        if response.status_code == 304:
            return ConnectorBatch(
                [], response_checkpoint, self._checkpoint_watermark(response_checkpoint)
            )
        parsed_at = datetime.now(tz=UTC)
        try:
            releases = response.json()
            if not isinstance(releases, list):
                raise ValueError("response is not a list")
        except (json.JSONDecodeError, ValueError) as exc:
            raise ConnectorError(f"invalid GitHub releases response: {exc}") from exc
        documents = [
            self._document(
                source_key=str(item.get("id") or item.get("tag_name")),
                title=str(item.get("name") or item.get("tag_name") or "GitHub release"),
                body=str(item.get("body") or item.get("name") or item.get("tag_name") or ""),
                url=item.get("html_url"),
                published_at=_parse_datetime(
                    item.get("published_at") or item.get("created_at"), parsed_at
                ),
                retrieved_at=parsed_at,
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
            )
            for item in releases
            if item.get("id") or item.get("tag_name")
        ]
        retrieved = datetime.now(tz=UTC)
        documents = [
            item.model_copy(update={"retrieved_at": retrieved, "available_at": retrieved})
            for item in documents
        ]
        return ConnectorBatch(
            documents,
            response_checkpoint,
            max(
                (item.published_at for item in documents),
                default=self._checkpoint_watermark(response_checkpoint),
            ),
        )


class SecEdgarConnector(_HttpConnector):
    async def fetch(self, checkpoint: dict[str, Any] | None = None) -> ConnectorBatch:
        raw_cik = str(self.config.get("cik") or "")
        if not raw_cik.isdigit() or not 1 <= len(raw_cik) <= 10 or int(raw_cik) == 0:
            raise ConnectorError("SEC connector requires a numeric CIK of at most 10 digits")
        cik = raw_cik.zfill(10)
        user_agent = str(self.config.get("user_agent") or "")
        if not cik.strip("0") or not user_agent:
            raise ConnectorError("SEC connector requires connector_config.cik and user_agent")
        url = str(self.config.get("url") or f"https://data.sec.gov/submissions/CIK{cik}.json")
        headers = {"User-Agent": user_agent, "Accept": "application/json"}
        headers.update(self._conditional_headers(checkpoint))
        response = await self._get(url, headers=headers)
        response_checkpoint = self._response_checkpoint(checkpoint, response)
        if response.status_code == 304:
            return ConnectorBatch(
                [], response_checkpoint, self._checkpoint_watermark(response_checkpoint)
            )
        try:
            payload = response.json()
            recent = payload["filings"]["recent"]
            accessions = recent["accessionNumber"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ConnectorError(f"invalid SEC submissions response: {exc}") from exc
        documents: list[DisclosureDocument] = []
        prior_seen_keys = [str(item) for item in (checkpoint or {}).get("seen_keys", [])]
        seen_keys = set(prior_seen_keys)
        max_documents = max(1, min(int(self.config.get("max_documents_per_run", 100)), 1000))
        for index, accession in enumerate(accessions):
            if len(documents) >= max_documents:
                break
            if str(accession) in seen_keys:
                continue
            form = _at(recent, "form", index)
            filing_date = _at(recent, "filingDate", index)
            primary = _at(recent, "primaryDocument", index)
            accession_path = str(accession).replace("-", "")
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_path}/{primary}"
                if primary
                else None
            )
            title = f"SEC {form} filing for {payload.get('name', cik)}"
            summary = " | ".join(
                value
                for value in [title, _at(recent, "primaryDocDescription", index), filing_date]
                if value
            )
            body = summary
            if filing_url and self.config.get("fetch_filing_body", True):
                filing_response = await self._get(
                    filing_url,
                    headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"},
                )
                normalized = html.unescape(_TAG.sub(" ", filing_response.text))
                body = " ".join(normalized.split()) or summary
            retrieved = datetime.now(tz=UTC)
            documents.append(
                self._document(
                    source_key=str(accession),
                    title=title,
                    body=body,
                    url=filing_url,
                    published_at=_parse_datetime(filing_date, datetime.now(tz=UTC)),
                    retrieved_at=retrieved,
                    etag=response.headers.get("etag"),
                    last_modified=response.headers.get("last-modified"),
                )
            )
        new_keys = [
            item.source_document_key for item in documents if item.source_document_key is not None
        ]
        response_checkpoint["seen_keys"] = list(dict.fromkeys(new_keys + prior_seen_keys))[:5000]
        return ConnectorBatch(
            documents,
            response_checkpoint,
            max(
                (item.published_at for item in documents),
                default=self._checkpoint_watermark(response_checkpoint),
            ),
        )


def build_connector(
    connector_type: str,
    *,
    policy_id: UUID,
    source_name: str,
    policy_version: str,
    trust_score: float,
    config: dict[str, Any],
    canonical_domains: list[str],
    client: httpx.AsyncClient,
    logical_source_key: str | None = None,
    resolve_host: Callable[[str], list[str]] | None = None,
    timeout_seconds: float = 15.0,
) -> DisclosureConnector:
    connector_class: type[_HttpConnector] | None = {
        "RSS_ATOM": OfficialFeedConnector,
        "GITHUB_RELEASES": GitHubReleasesConnector,
        "SEC_EDGAR": SecEdgarConnector,
    }.get(connector_type.upper())
    if connector_class is None:
        raise ConnectorError(f"unsupported connector type: {connector_type}")
    defaults = {
        "GITHUB_RELEASES": ["api.github.com", "github.com"],
        "SEC_EDGAR": ["data.sec.gov", "www.sec.gov"],
    }.get(connector_type.upper(), [])
    approved_domains = canonical_domains or defaults
    if not approved_domains:
        raise ConnectorError(f"{connector_type} connector requires canonical_domains")
    connector_config = dict(config)
    connector_config["logical_source_key"] = logical_source_key or source_name
    return connector_class(
        policy_id=policy_id,
        source_name=source_name,
        policy_version=policy_version,
        trust_score=trust_score,
        config=connector_config,
        canonical_domains=approved_domains,
        client=client,
        resolve_host=resolve_host or _resolve_host,
        timeout_seconds=timeout_seconds,
    )


def _resolve_host(host: str) -> list[str]:
    return sorted(
        {
            str(sockaddr[0])
            for _, _, _, _, sockaddr in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
    )


def _xml_text(element: ET.Element, local_name: str) -> str | None:
    for child in element.iter():
        if child.tag.rsplit("}", 1)[-1] == local_name and child.text:
            return child.text.strip()
    return None


def _entry_link(entry: ET.Element) -> str | None:
    for child in entry.iter():
        if child.tag.rsplit("}", 1)[-1] == "link":
            return child.attrib.get("href") or (child.text.strip() if child.text else None)
    return None


def _parse_datetime(value: Any, fallback: datetime) -> datetime:
    if not value:
        return fallback
    text = str(value).strip()
    try:
        parsed = (
            parsedate_to_datetime(text)
            if "," in text
            else datetime.fromisoformat(text.replace("Z", "+00:00"))
        )
        return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)
    except (TypeError, ValueError):
        return fallback


def _at(values: dict[str, Any], key: str, index: int) -> str:
    items = values.get(key, [])
    return str(items[index]) if isinstance(items, list) and index < len(items) else ""

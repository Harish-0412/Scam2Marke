import hashlib
import ipaddress
import re
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit
from uuid import NAMESPACE_URL, UUID, uuid5


class IndicatorType(StrEnum):
    domain = "DOMAIN"
    url = "URL"
    ipv4 = "IPV4"
    ipv6 = "IPV6"
    md5 = "MD5"
    sha1 = "SHA1"
    sha256 = "SHA256"
    email = "EMAIL"
    wallet = "WALLET"


@dataclass(frozen=True, slots=True)
class NormalizedIndicator:
    type: IndicatorType
    value: str
    value_hash: str
    indicator_id: str


_TYPE_MAP = {
    "domain": IndicatorType.domain,
    "hostname": IndicatorType.domain,
    "url": IndicatorType.url,
    "uri": IndicatorType.url,
    "ipv4": IndicatorType.ipv4,
    "ipv6": IndicatorType.ipv6,
    "md5": IndicatorType.md5,
    "filehash-md5": IndicatorType.md5,
    "sha1": IndicatorType.sha1,
    "filehash-sha1": IndicatorType.sha1,
    "sha256": IndicatorType.sha256,
    "filehash-sha256": IndicatorType.sha256,
    "email": IndicatorType.email,
    "email-address": IndicatorType.email,
    "bitcoinaddress": IndicatorType.wallet,
    "cryptocurrency-address": IndicatorType.wallet,
}


def normalize_indicator(raw_type: str, raw_value: str) -> NormalizedIndicator:
    try:
        kind = _TYPE_MAP[raw_type.strip().lower()]
    except KeyError as exc:
        raise ValueError("unsupported indicator type") from exc
    value = raw_value.strip()
    if kind == IndicatorType.domain:
        value = _domain(value)
    elif kind == IndicatorType.url:
        value = _url(value)
    elif kind in {IndicatorType.ipv4, IndicatorType.ipv6}:
        address = ipaddress.ip_address(value)
        if address.version != (4 if kind == IndicatorType.ipv4 else 6):
            raise ValueError("IP version does not match indicator type")
        value = address.compressed
    elif kind in {IndicatorType.md5, IndicatorType.sha1, IndicatorType.sha256}:
        expected = {IndicatorType.md5: 32, IndicatorType.sha1: 40, IndicatorType.sha256: 64}[kind]
        value = value.lower()
        if len(value) != expected or not re.fullmatch(r"[0-9a-f]+", value):
            raise ValueError("invalid hash indicator")
    elif kind == IndicatorType.email:
        local, separator, domain = value.rpartition("@")
        if not separator or not local:
            raise ValueError("invalid email indicator")
        value = f"{local.lower()}@{_domain(domain)}"
    elif kind == IndicatorType.wallet and not re.fullmatch(r"[A-Za-z0-9]{26,128}", value):
        raise ValueError("invalid wallet indicator")
    identity = f"{kind.value}:{value}"
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return NormalizedIndicator(kind, value, digest, str(uuid5(NAMESPACE_URL, identity)))


def match_candidates(text: str, urls: list[str]) -> set[tuple[IndicatorType, str]]:
    candidates: set[tuple[IndicatorType, str]] = set()
    for raw_url in urls:
        try:
            url = _url(raw_url)
        except ValueError:
            continue
        candidates.add((IndicatorType.url, url))
        host = urlsplit(url).hostname
        if host:
            candidates.add((IndicatorType.domain, host))
    for token in re.findall(r"[A-Za-z0-9:@._/%?=&+-]+", text):
        cleaned = token.strip(".,;()[]")
        if cleaned.startswith(("http://", "https://")):
            try:
                normalized_url = _url(cleaned)
                candidates.add((IndicatorType.url, normalized_url))
                host = urlsplit(normalized_url).hostname
                if host:
                    candidates.add((IndicatorType.domain, host))
            except ValueError:
                pass
        elif "." in cleaned:
            with suppress(ValueError):
                candidates.add((IndicatorType.domain, _domain(cleaned)))
        for kind in (
            IndicatorType.ipv4,
            IndicatorType.ipv6,
            IndicatorType.md5,
            IndicatorType.sha1,
            IndicatorType.sha256,
        ):
            try:
                item = normalize_indicator(kind.value, cleaned)
            except ValueError:
                continue
            candidates.add((item.type, item.value))
    return candidates


def deterministic_match_id(
    scope_id: str, asset_id: str, post_id: str, observation_id: UUID
) -> UUID:
    return uuid5(NAMESPACE_URL, f"threat-match:{scope_id}:{asset_id}:{post_id}:{observation_id}")


def _domain(value: str) -> str:
    domain = value.rstrip(".").lower().encode("idna").decode("ascii")
    if (
        len(domain) > 253
        or not domain
        or any(
            not label
            or len(label) > 63
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
            for label in domain.split(".")
        )
    ):
        raise ValueError("invalid domain indicator")
    return domain


def _url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("invalid URL indicator")
    host = _domain(parts.hostname)
    port = f":{parts.port}" if parts.port and parts.port not in {80, 443} else ""
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), host + port, path, parts.query, ""))

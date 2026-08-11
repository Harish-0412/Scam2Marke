from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from jwt import PyJWKClient
from sqlalchemy import select
from starlette.requests import HTTPConnection

from scam2market.config.settings import get_settings
from scam2market.db.models import AuthEventModel, ServiceAccountKeyModel, ServiceAccountModel
from scam2market.db.session import AsyncSessionLocal


class Role(StrEnum):
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    TENANT_ADMIN = "TENANT_ADMIN"
    ANALYST = "ANALYST"
    REVIEWER = "REVIEWER"
    VIEWER = "VIEWER"
    SERVICE = "SERVICE"


ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.PLATFORM_ADMIN: frozenset({"*"}),
    Role.TENANT_ADMIN: frozenset(
        {"tenant:manage", "service-account:manage", "investigation:write", "alert:write", "read"}
    ),
    Role.ANALYST: frozenset({"investigation:write", "alert:write", "feedback:write", "read"}),
    Role.REVIEWER: frozenset({"feedback:adjudicate", "policy:approve", "read"}),
    Role.VIEWER: frozenset({"read"}),
    Role.SERVICE: frozenset({"ingestion:write", "checkpoint:write", "read"}),
}


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    tenant_id: str
    roles: frozenset[Role]
    auth_method: str
    service_account_id: UUID | None = None

    def has_permission(self, permission: str) -> bool:
        return any(
            "*" in ROLE_PERMISSIONS[role] or permission in ROLE_PERMISSIONS[role]
            for role in self.roles
        )


def generate_service_key() -> tuple[str, str, str]:
    key_id = secrets.token_hex(8)
    secret = secrets.token_urlsafe(32)
    return key_id, secret, f"s2m_{key_id}.{secret}"


def hash_service_secret(key_id: str, secret: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), f"{key_id}.{secret}".encode(), hashlib.sha256).hexdigest()


def parse_service_key(raw_key: str) -> tuple[str, str] | None:
    if not raw_key.startswith("s2m_") or "." not in raw_key:
        return None
    key_id, secret = raw_key[4:].split(".", 1)
    if len(key_id) != 16 or not secret:
        return None
    return key_id, secret


def normalize_roles(value: Any) -> frozenset[Role]:
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        values = [str(item) for item in value]
    else:
        values = []
    try:
        return frozenset(Role(item.upper()) for item in values if item)
    except ValueError as exc:
        raise HTTPException(
            status_code=403, detail="identity contains an unsupported role"
        ) from exc


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True)


def _decode_oidc_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.oidc_issuer or not settings.oidc_audience or not settings.oidc_jwks_url:
        raise HTTPException(status_code=503, detail="OIDC is not configured")
    try:
        signing_key = _jwks_client(settings.oidc_jwks_url).get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid or expired access token") from exc
    return dict(payload)


async def _authenticate_service_key(raw_key: str) -> Principal:
    parsed = parse_service_key(raw_key)
    if parsed is None:
        raise HTTPException(status_code=401, detail="invalid service account key")
    key_id, secret = parsed
    now = datetime.now(tz=UTC)
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ServiceAccountKeyModel, ServiceAccountModel)
            .join(
                ServiceAccountModel,
                ServiceAccountModel.service_account_id == ServiceAccountKeyModel.service_account_id,
            )
            .where(ServiceAccountKeyModel.key_id == key_id)
        )
        row = result.one_or_none()
        if row is None:
            raise HTTPException(status_code=401, detail="invalid service account key")
        key, account = row
        candidate = hash_service_secret(key_id, secret, settings.service_key_pepper)
        valid = (
            hmac.compare_digest(candidate, key.secret_hash)
            and key.revoked_at is None
            and key.expires_at > now
            and account.status == "ACTIVE"
        )
        if not valid:
            raise HTTPException(status_code=401, detail="invalid or expired service account key")
        key.last_used_at = now
        session.add(
            AuthEventModel(
                tenant_id=account.tenant_id,
                subject=f"service-account:{account.service_account_id}",
                event_type="SERVICE_KEY_AUTHENTICATED",
                auth_method="service_key",
                success=True,
                metadata_json={"key_id": key.key_id},
            )
        )
        await session.commit()
        return Principal(
            subject=f"service-account:{account.service_account_id}",
            tenant_id=account.tenant_id,
            roles=normalize_roles(account.roles_json),
            auth_method="service_key",
            service_account_id=account.service_account_id,
        )


async def authenticate_request(request: HTTPConnection) -> Principal:
    cached = getattr(request.state, "principal", None)
    if isinstance(cached, Principal):
        return cached
    settings = get_settings()
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        principal = (
            await _authenticate_service_key(token)
            if token.startswith("s2m_")
            else _principal_from_oidc(_decode_oidc_token(token))
        )
    elif (
        settings.environment.lower() in {"development", "test"}
        and settings.development_auth_enabled
    ):
        principal = Principal(
            subject=request.headers.get("x-dev-subject", "local-admin"),
            tenant_id=request.headers.get("x-tenant-id", settings.default_tenant_id),
            roles=normalize_roles(
                request.headers.get("x-dev-roles", "PLATFORM_ADMIN,TENANT_ADMIN,ANALYST,REVIEWER")
            ),
            auth_method="development",
        )
    elif settings.auth_required:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    else:
        principal = Principal(
            subject="anonymous-readonly",
            tenant_id=settings.default_tenant_id,
            roles=frozenset({Role.VIEWER}),
            auth_method="anonymous",
        )
    request.state.principal = principal
    return principal


def _principal_from_oidc(payload: dict[str, Any]) -> Principal:
    settings = get_settings()
    tenant_id = payload.get(settings.oidc_tenant_claim)
    if not tenant_id:
        raise HTTPException(status_code=403, detail="access token has no tenant claim")
    roles = normalize_roles(payload.get(settings.oidc_roles_claim, []))
    if not roles:
        raise HTTPException(status_code=403, detail="access token has no authorized roles")
    return Principal(
        subject=str(payload["sub"]),
        tenant_id=str(tenant_id),
        roles=roles,
        auth_method="oidc",
    )


CurrentPrincipal = Annotated[Principal, Depends(authenticate_request)]


def require_permission(permission: str) -> Any:
    async def dependency(principal: CurrentPrincipal) -> Principal:
        if not principal.has_permission(permission):
            raise HTTPException(status_code=403, detail=f"permission required: {permission}")
        return principal

    return dependency


async def authorize_api_request(request: HTTPConnection, principal: CurrentPrincipal) -> Principal:
    method = str(request.scope.get("method", "GET"))
    required: tuple[str, ...]
    if method in {"GET", "HEAD", "OPTIONS"}:
        required = ("read",)
    elif request.url.path.endswith("/decision") or "/models/" in request.url.path:
        required = ("policy:approve",)
    elif "/operations/model-drift" in request.url.path or "/surveillance" in request.url.path:
        required = ("ingestion:write",)
    else:
        required = ("investigation:write", "alert:write", "feedback:write")
    if not any(principal.has_permission(permission) for permission in required):
        raise HTTPException(
            status_code=403, detail=f"one permission required: {', '.join(required)}"
        )
    return principal

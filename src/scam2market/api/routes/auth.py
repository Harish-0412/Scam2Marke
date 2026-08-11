from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scam2market.config.settings import get_settings
from scam2market.db.models import (
    ServiceAccountKeyModel,
    ServiceAccountModel,
    TenantModel,
    UserMembershipModel,
)
from scam2market.db.session import get_db_session
from scam2market.security.auth import (
    CurrentPrincipal,
    Role,
    generate_service_key,
    hash_service_secret,
    normalize_roles,
    require_permission,
)

router = APIRouter(prefix="/auth")


class TenantCreate(BaseModel):
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
    name: str = Field(min_length=2, max_length=255)


class MembershipCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    roles: list[Role] = Field(min_length=1)


class ServiceAccountCreate(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    roles: list[Role] = Field(default_factory=lambda: [Role.SERVICE])
    ttl_days: int | None = Field(default=None, ge=1, le=365)


@router.get("/me")
async def get_current_identity(principal: CurrentPrincipal) -> dict[str, Any]:
    return {
        "subject": principal.subject,
        "tenant_id": principal.tenant_id,
        "roles": sorted(role.value for role in principal.roles),
        "permissions": sorted(
            {permission for role in principal.roles for permission in _permissions_for(role)}
        ),
        "auth_method": principal.auth_method,
        "service_account_id": principal.service_account_id,
    }


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
    _: Any = Depends(require_permission("*")),
) -> dict[str, Any]:
    if await session.get(TenantModel, body.tenant_id) is not None:
        raise HTTPException(status_code=409, detail="tenant already exists")
    tenant = TenantModel(tenant_id=body.tenant_id, name=body.name)
    membership = UserMembershipModel(
        tenant_id=body.tenant_id,
        subject=principal.subject,
        roles_json=[Role.TENANT_ADMIN.value],
    )
    session.add_all([tenant, membership])
    await session.commit()
    return {"tenant_id": tenant.tenant_id, "name": tenant.name, "status": tenant.status}


@router.post("/memberships", status_code=status.HTTP_201_CREATED)
async def create_membership(
    body: MembershipCreate,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
    _: Any = Depends(require_permission("tenant:manage")),
) -> dict[str, Any]:
    roles = normalize_roles([role.value for role in body.roles])
    if Role.PLATFORM_ADMIN in roles and Role.PLATFORM_ADMIN not in principal.roles:
        raise HTTPException(status_code=403, detail="only platform admins can grant that role")
    row = UserMembershipModel(
        tenant_id=principal.tenant_id,
        subject=body.subject,
        roles_json=sorted(role.value for role in roles),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {
        "membership_id": row.membership_id,
        "tenant_id": row.tenant_id,
        "subject": row.subject,
        "roles": row.roles_json,
    }


@router.post("/service-accounts", status_code=status.HTTP_201_CREATED)
async def create_service_account(
    body: ServiceAccountCreate,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
    _: Any = Depends(require_permission("service-account:manage")),
) -> dict[str, Any]:
    allowed_roles = {Role.SERVICE, Role.VIEWER}
    if not set(body.roles).issubset(allowed_roles):
        raise HTTPException(
            status_code=422,
            detail="service accounts may only receive SERVICE and VIEWER roles",
        )
    account = ServiceAccountModel(
        tenant_id=principal.tenant_id,
        name=body.name,
        roles_json=sorted(role.value for role in body.roles),
        created_by=principal.subject,
    )
    session.add(account)
    await session.flush()
    key, raw_key = _new_key(account.service_account_id, principal.subject, body.ttl_days)
    session.add(key)
    await session.commit()
    return _account_response(account, raw_key=raw_key, key=key)


@router.get("/service-accounts")
async def list_service_accounts(
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
    _: Any = Depends(require_permission("service-account:manage")),
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(ServiceAccountModel)
            .where(ServiceAccountModel.tenant_id == principal.tenant_id)
            .order_by(ServiceAccountModel.created_at.desc())
        )
    ).all()
    return [_account_response(row) for row in rows]


@router.post("/service-accounts/{account_id}/keys/{key_id}/rotate")
async def rotate_service_key(
    account_id: UUID,
    key_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
    _: Any = Depends(require_permission("service-account:manage")),
) -> dict[str, Any]:
    account = await session.scalar(
        select(ServiceAccountModel)
        .where(
            ServiceAccountModel.service_account_id == account_id,
            ServiceAccountModel.tenant_id == principal.tenant_id,
        )
        .with_for_update()
    )
    old_key = await session.scalar(
        select(ServiceAccountKeyModel)
        .where(
            ServiceAccountKeyModel.key_id == key_id,
            ServiceAccountKeyModel.service_account_id == account_id,
        )
        .with_for_update()
    )
    if account is None or old_key is None:
        raise HTTPException(status_code=404, detail="service account key not found")
    if old_key.revoked_at is not None:
        raise HTTPException(status_code=409, detail="service account key is already revoked")
    old_key.revoked_at = datetime.now(tz=UTC)
    key, raw_key = _new_key(account_id, principal.subject, rotated_from=old_key.key_id)
    session.add(key)
    await session.commit()
    return _account_response(account, raw_key=raw_key, key=key)


@router.delete("/service-accounts/{account_id}/keys/{key_id}", status_code=204)
async def revoke_service_key(
    account_id: UUID,
    key_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession = Depends(get_db_session),
    _: Any = Depends(require_permission("service-account:manage")),
) -> None:
    key = await session.scalar(
        select(ServiceAccountKeyModel)
        .join(ServiceAccountModel)
        .where(
            ServiceAccountKeyModel.key_id == key_id,
            ServiceAccountKeyModel.service_account_id == account_id,
            ServiceAccountModel.tenant_id == principal.tenant_id,
        )
        .with_for_update()
    )
    if key is None:
        raise HTTPException(status_code=404, detail="service account key not found")
    key.revoked_at = key.revoked_at or datetime.now(tz=UTC)
    await session.commit()


def _new_key(
    account_id: UUID,
    actor: str,
    ttl_days: int | None = None,
    *,
    rotated_from: str | None = None,
) -> tuple[ServiceAccountKeyModel, str]:
    settings = get_settings()
    key_id, secret, raw_key = generate_service_key()
    ttl = ttl_days or settings.service_key_default_ttl_days
    return (
        ServiceAccountKeyModel(
            key_id=key_id,
            service_account_id=account_id,
            secret_hash=hash_service_secret(key_id, secret, settings.service_key_pepper),
            key_prefix=f"s2m_{key_id}",
            created_by=actor,
            expires_at=datetime.now(tz=UTC) + timedelta(days=ttl),
            rotated_from_key_id=rotated_from,
        ),
        raw_key,
    )


def _account_response(
    account: ServiceAccountModel,
    *,
    raw_key: str | None = None,
    key: ServiceAccountKeyModel | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "service_account_id": account.service_account_id,
        "tenant_id": account.tenant_id,
        "name": account.name,
        "roles": account.roles_json,
        "status": account.status,
    }
    if raw_key is not None and key is not None:
        result["key"] = {
            "key_id": key.key_id,
            "secret": raw_key,
            "expires_at": key.expires_at,
            "displayed_once": True,
        }
    return result


def _permissions_for(role: Role) -> set[str]:
    from scam2market.security.auth import ROLE_PERMISSIONS

    return set(ROLE_PERMISSIONS[role])

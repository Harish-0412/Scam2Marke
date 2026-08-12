from uuid import uuid4

from fastapi.testclient import TestClient

from scam2market.config.settings import get_settings
from scam2market.main import create_app
from scam2market.security.auth import (
    Role,
    generate_service_key,
    hash_service_secret,
    normalize_roles,
    parse_service_key,
)


def test_service_key_material_is_parseable_and_peppered() -> None:
    key_id, secret, raw_key = generate_service_key()
    assert parse_service_key(raw_key) == (key_id, secret)
    assert hash_service_secret(key_id, secret, "pepper-a") != hash_service_secret(
        key_id, secret, "pepper-b"
    )
    assert parse_service_key("invalid") is None


def test_role_normalization_is_canonical() -> None:
    assert normalize_roles("viewer,analyst") == frozenset({Role.VIEWER, Role.ANALYST})


def test_viewer_cannot_mutate_protected_resources() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/watchlists",
            headers={
                "X-Dev-Roles": "VIEWER",
                "X-Actor-ID": "readonly-user",
            },
            json={"name": "blocked", "scope_id": "LIVE"},
        )
    assert response.status_code == 403


def test_tenants_are_isolated_and_service_keys_rotate() -> None:
    suffix = uuid4().hex[:10]
    tenant_a = f"tenant-a-{suffix}"
    tenant_b = f"tenant-b-{suffix}"
    actor_a = f"analyst-a-{suffix}"
    actor_b = f"analyst-b-{suffix}"
    with TestClient(create_app()) as client:
        for tenant_id in (tenant_a, tenant_b):
            response = client.post(
                "/api/v1/auth/tenants",
                json={"tenant_id": tenant_id, "name": tenant_id},
            )
            assert response.status_code == 201, response.text

        response = client.post(
            "/api/v1/watchlists",
            headers={"X-Tenant-ID": tenant_a, "X-Actor-ID": actor_a},
            json={"name": f"tenant-a-watchlist-{suffix}", "scope_id": "LIVE"},
        )
        assert response.status_code == 201, response.text
        response = client.post(
            "/api/v1/watchlists",
            headers={"X-Tenant-ID": tenant_b, "X-Actor-ID": actor_b},
            json={"name": f"tenant-b-watchlist-{suffix}", "scope_id": "LIVE"},
        )
        assert response.status_code == 201, response.text

        response = client.get(
            "/api/v1/watchlists",
            headers={"X-Tenant-ID": tenant_a, "X-Actor-ID": actor_a},
        )
        assert response.status_code == 200
        assert [item["name"] for item in response.json()] == [f"tenant-a-watchlist-{suffix}"]

        created = client.post(
            "/api/v1/auth/service-accounts",
            headers={"X-Tenant-ID": tenant_a},
            json={"name": "feature-worker", "roles": ["SERVICE"]},
        )
        assert created.status_code == 201, created.text
        payload = created.json()
        account_id = payload["service_account_id"]
        old_key_id = payload["key"]["key_id"]
        old_secret = payload["key"]["secret"]

        identity = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_secret}"})
        assert identity.status_code == 200, identity.text
        assert identity.json()["tenant_id"] == tenant_a

        rotated = client.post(
            f"/api/v1/auth/service-accounts/{account_id}/keys/{old_key_id}/rotate",
            headers={"X-Tenant-ID": tenant_a},
        )
        assert rotated.status_code == 200, rotated.text
        new_secret = rotated.json()["key"]["secret"]
        assert new_secret != old_secret
        assert (
            client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {old_secret}"}
            ).status_code
            == 401
        )
        assert (
            client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {new_secret}"}
            ).status_code
            == 200
        )


def test_production_mode_requires_authentication() -> None:
    settings = get_settings()
    old_environment = settings.environment
    old_required = settings.auth_required
    old_development = settings.development_auth_enabled
    try:
        settings.environment = "production"
        settings.auth_required = True
        settings.development_auth_enabled = False
        with TestClient(create_app()) as client:
            response = client.get("/api/v1/campaigns")
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
    finally:
        settings.environment = old_environment
        settings.auth_required = old_required
        settings.development_auth_enabled = old_development

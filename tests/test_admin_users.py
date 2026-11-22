"""Tests for System Admin user listing, inspection, and activation/deactivation."""

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient


def test_admin_can_list_paginated_users_and_filter(
    client: TestClient,
    register_user: Callable[..., dict[str, Any]],
    admin_headers: dict[str, str],
) -> None:
    register_user(email="u1@example.org", full_name="Alpha Researcher", affiliation="MIT")
    register_user(email="u2@example.org", full_name="Beta Scientist", affiliation="Stanford")
    register_user(email="u3@example.org", full_name="Gamma Scholar", affiliation="Oxford")

    # 3 registered users + 1 admin_user = 4 total
    page1 = client.get("/api/v1/admin/users?page=1&page_size=2", headers=admin_headers)
    assert page1.status_code == 200
    body1 = page1.json()
    assert body1["page"] == 1
    assert body1["page_size"] == 2
    assert body1["total"] == 4
    assert len(body1["items"]) == 2

    page2 = client.get("/api/v1/admin/users?page=2&page_size=2", headers=admin_headers)
    assert page2.status_code == 200
    body2 = page2.json()
    assert body2["page"] == 2
    assert body2["total"] == 4
    assert len(body2["items"]) == 2

    ids_page1 = {item["id"] for item in body1["items"]}
    ids_page2 = {item["id"] for item in body2["items"]}
    assert ids_page1.isdisjoint(ids_page2)

    search_res = client.get("/api/v1/admin/users?search=stanford", headers=admin_headers)
    assert search_res.status_code == 200
    search_body = search_res.json()
    assert search_body["total"] == 1
    assert search_body["items"][0]["email"] == "u2@example.org"


def test_admin_can_inspect_and_toggle_user_active_status(
    client: TestClient,
    register_user: Callable[..., dict[str, Any]],
    admin_user: dict[str, Any],
    admin_headers: dict[str, str],
) -> None:
    target = register_user(email="target@example.org", password="TargetPass123!")

    detail = client.get(f"/api/v1/admin/users/{target['id']}", headers=admin_headers)
    assert detail.status_code == 200
    assert detail.json()["email"] == "target@example.org"
    assert detail.json()["is_active"] is True

    # Deactivate
    deactivated = client.patch(
        f"/api/v1/admin/users/{target['id']}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    # Filter inactive users
    inactive_list = client.get("/api/v1/admin/users?is_active=false", headers=admin_headers)
    assert inactive_list.status_code == 200
    assert inactive_list.json()["total"] == 1
    assert inactive_list.json()["items"][0]["id"] == target["id"]

    # Reactivate
    reactivated = client.patch(
        f"/api/v1/admin/users/{target['id']}",
        headers=admin_headers,
        json={"is_active": True},
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True

    # Reactivated user can log in again
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "target@example.org", "password": "TargetPass123!"},
    )
    assert login_res.status_code == 200

    # Admin cannot deactivate themselves
    self_deactivate = client.patch(
        f"/api/v1/admin/users/{admin_user['id']}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert self_deactivate.status_code == 400
    assert self_deactivate.json()["code"] == "cannot_deactivate_self"

    # Missing user returns 404
    missing = client.get("/api/v1/admin/users/999999", headers=admin_headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == "user_not_found"


def test_non_admin_user_receives_403_on_admin_endpoints(
    client: TestClient,
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    regular = register_user(email="nonadmin@example.org", password="Password123!")
    headers = auth_headers_for(email="nonadmin@example.org", password="Password123!")

    list_res = client.get("/api/v1/admin/users", headers=headers)
    assert list_res.status_code == 403
    assert list_res.json()["code"] == "admin_required"

    detail_res = client.get(f"/api/v1/admin/users/{regular['id']}", headers=headers)
    assert detail_res.status_code == 403
    assert detail_res.json()["code"] == "admin_required"

    patch_res = client.patch(
        f"/api/v1/admin/users/{regular['id']}",
        headers=headers,
        json={"is_active": False},
    )
    assert patch_res.status_code == 403
    assert patch_res.json()["code"] == "admin_required"

    # Unauthenticated caller gets 401
    unauth_res = client.get("/api/v1/admin/users")
    assert unauth_res.status_code == 401
    assert unauth_res.json()["code"] == "unauthorized"

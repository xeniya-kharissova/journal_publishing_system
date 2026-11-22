"""Tests for authenticated user profile retrieval and updates (GET/PATCH /api/v1/users/me)."""

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient


def test_get_and_patch_own_profile(
    client: TestClient,
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    register_user(
        email="profile@university.edu",
        password="ProfilePass123!",
        full_name="Dr. Initial Name",
        affiliation="Initial University",
    )
    headers = auth_headers_for(email="profile@university.edu", password="ProfilePass123!")

    initial_res = client.get("/api/v1/users/me", headers=headers)
    assert initial_res.status_code == 200
    initial = initial_res.json()
    assert initial["full_name"] == "Dr. Initial Name"
    assert initial["affiliation"] == "Initial University"
    assert initial["bio"] is None
    assert initial["orcid"] is None
    assert initial["expertise_keywords"] == []
    assert initial["max_active_reviews"] == 5

    patch_res = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={
            "full_name": "Prof. Updated Name",
            "affiliation": "Updated Institute",
            "bio": "Researching distributed systems and peer review.",
            "orcid": "0000-0002-1825-0097",
            "expertise_keywords": ["Distributed Systems", "Peer Review", "distributed systems", "  "],
            "max_active_reviews": 8,
        },
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["full_name"] == "Prof. Updated Name"
    assert updated["affiliation"] == "Updated Institute"
    assert updated["bio"] == "Researching distributed systems and peer review."
    assert updated["orcid"] == "0000-0002-1825-0097"
    assert updated["expertise_keywords"] == ["Distributed Systems", "Peer Review"]
    assert updated["max_active_reviews"] == 8

    # Verify persistence via a subsequent GET
    persisted = client.get("/api/v1/users/me", headers=headers).json()
    assert persisted["full_name"] == "Prof. Updated Name"
    assert persisted["orcid"] == "0000-0002-1825-0097"
    assert persisted["max_active_reviews"] == 8

    # Partial update leaves unspecified fields intact and can clear nullable fields
    partial_res = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"bio": None},
    )
    assert partial_res.status_code == 200
    partial = partial_res.json()
    assert partial["bio"] is None
    assert partial["full_name"] == "Prof. Updated Name"
    assert partial["orcid"] == "0000-0002-1825-0097"


def test_profile_endpoints_require_valid_access_token(
    client: TestClient,
    register_user: Callable[..., dict[str, Any]],
    login_user: Callable[..., dict[str, Any]],
) -> None:
    no_auth = client.get("/api/v1/users/me")
    assert no_auth.status_code == 401
    assert no_auth.json()["code"] == "unauthorized"

    register_user(email="tokenonly@university.edu", password="Password123!")
    tokens = login_user(email="tokenonly@university.edu", password="Password123!")

    # Refresh token must not be accepted as a Bearer access token
    refresh_as_access = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
    )
    assert refresh_as_access.status_code == 401
    assert refresh_as_access.json()["code"] == "invalid_token_type"


def test_profile_patch_validation_and_privilege_protection(
    client: TestClient,
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    register_user(email="regular@university.edu", password="Password123!")
    headers = auth_headers_for(email="regular@university.edu", password="Password123!")

    bad_capacity = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"max_active_reviews": -1},
    )
    assert bad_capacity.status_code == 422
    assert bad_capacity.json()["code"] == "validation_error"

    # Attempting to escalate privileges via extra fields is ignored
    escalation_attempt = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"is_system_admin": True, "is_active": False, "affiliation": "Safe Lab"},
    )
    assert escalation_attempt.status_code == 200
    body = escalation_attempt.json()
    assert body["is_system_admin"] is False
    assert body["is_active"] is True
    assert body["affiliation"] == "Safe Lab"

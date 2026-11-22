"""Tests for user registration, JWT login, token refresh, and deactivated-account denial."""

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient


def test_register_user_success(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "  Alice.Researcher@Example.EDU  ",
            "password": "StrongPassword123!",
            "full_name": "Dr. Alice Researcher",
            "affiliation": "Institute of Computing",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["email"] == "alice.researcher@example.edu"
    assert body["full_name"] == "Dr. Alice Researcher"
    assert body["affiliation"] == "Institute of Computing"
    assert body["is_active"] is True
    assert body["is_system_admin"] is False
    assert "password_hash" not in body
    assert "password" not in body


def test_register_duplicate_email_returns_409_conflict(
    client: TestClient,
    register_user: Callable[..., dict[str, Any]],
) -> None:
    register_user(email="duplicate@university.edu")

    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "DUPLICATE@University.EDU",
            "password": "AnotherPassword123!",
            "full_name": "Second User",
            "affiliation": "Other Lab",
        },
    )
    assert response.status_code == 409
    body = response.json()
    assert set(body.keys()) == {"code", "message", "details"}
    assert body["code"] == "email_already_registered"


def test_register_short_password_rejected_with_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "shortpass@university.edu",
            "password": "short",
            "full_name": "Short Pass",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_login_and_refresh_token_lifecycle(
    client: TestClient,
    register_user: Callable[..., dict[str, Any]],
) -> None:
    register_user(email="bob@university.edu", password="BobPassword123!")

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "BOB@University.edu", "password": "BobPassword123!"},
    )
    assert login_response.status_code == 200
    tokens = login_response.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] > 0
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    me_response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "bob@university.edu"

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh_response.status_code == 200
    refreshed = refresh_response.json()
    assert refreshed["access_token"]
    assert refreshed["refresh_token"]

    me_after_refresh = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {refreshed['access_token']}"},
    )
    assert me_after_refresh.status_code == 200
    assert me_after_refresh.json()["email"] == "bob@university.edu"


def test_login_invalid_credentials_returns_401(
    client: TestClient,
    register_user: Callable[..., dict[str, Any]],
) -> None:
    register_user(email="carol@university.edu", password="CorrectPassword123!")

    wrong_pw = client.post(
        "/api/v1/auth/login",
        json={"email": "carol@university.edu", "password": "WrongPassword!"},
    )
    assert wrong_pw.status_code == 401
    assert wrong_pw.json()["code"] == "invalid_credentials"

    unknown_email = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@university.edu", "password": "CorrectPassword123!"},
    )
    assert unknown_email.status_code == 401
    assert unknown_email.json()["code"] == "invalid_credentials"


def test_refresh_rejects_access_token_and_malformed_token(
    client: TestClient,
    register_user: Callable[..., dict[str, Any]],
    login_user: Callable[..., dict[str, Any]],
) -> None:
    register_user(email="dave@university.edu", password="DavePassword123!")
    tokens = login_user(email="dave@university.edu", password="DavePassword123!")

    wrong_type = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["access_token"]},
    )
    assert wrong_type.status_code == 401
    assert wrong_type.json()["code"] == "invalid_token_type"

    malformed = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "not.a.valid.jwt"},
    )
    assert malformed.status_code == 401
    assert malformed.json()["code"] == "invalid_token"


def test_deactivated_user_denied_login_refresh_and_api_access(
    client: TestClient,
    register_user: Callable[..., dict[str, Any]],
    login_user: Callable[..., dict[str, Any]],
    admin_headers: dict[str, str],
) -> None:
    created = register_user(email="eve@university.edu", password="EvePassword123!")
    tokens = login_user(email="eve@university.edu", password="EvePassword123!")

    deactivate_res = client.patch(
        f"/api/v1/admin/users/{created['id']}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert deactivate_res.status_code == 200
    assert deactivate_res.json()["is_active"] is False

    # Previously issued access token must be rejected
    api_res = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert api_res.status_code == 403
    assert api_res.json()["code"] == "account_deactivated"

    # Refresh token must be rejected
    refresh_res = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh_res.status_code == 403
    assert refresh_res.json()["code"] == "account_deactivated"

    # Fresh login must be rejected
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "eve@university.edu", "password": "EvePassword123!"},
    )
    assert login_res.status_code == 403
    assert login_res.json()["code"] == "account_deactivated"

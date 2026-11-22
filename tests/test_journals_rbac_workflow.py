"""HTTP API tests for multi-journal management, per-journal RBAC isolation, and workflow config."""

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient


def _create_journal(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    title: str = "Journal of Software Analysis",
    slug: str = "journal-software-analysis",
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "title": title,
        "slug": slug,
        "issn": "2049-3630",
        "description": "Peer-reviewed software engineering research.",
        "scope_keywords": ["Software Architecture", "Testing", "testing"],
        "publisher_name": "Open Scholarly Press",
        "doi_prefix": "10.5555",
        "apc_enabled": True,
        "apc_amount_cents": 150000,
        "apc_currency": "usd",
        **extra,
    }
    response = client.post("/api/v1/journals", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_admin_journal_lifecycle_defaults_and_unique_slug(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    created = _create_journal(client, admin_headers)
    assert created["slug"] == "journal-software-analysis"
    assert created["scope_keywords"] == ["Software Architecture", "Testing"]
    assert created["doi_prefix"] == "10.5555"
    assert created["apc_enabled"] is True
    assert created["apc_amount_cents"] == 150000
    assert created["apc_currency"] == "USD"
    assert created["is_active"] is True

    # Default editorial workflow configuration is automatically initialized
    wf = created["workflow_config"]
    assert wf["anonymity_mode"] == "double_anonymous"
    assert wf["min_reviewers"] == 2
    assert wf["require_desk_review"] is True
    assert wf["require_plagiarism_check"] is False
    assert wf["desk_review_sla_days"] > 0
    assert wf["review_sla_days"] > 0
    assert wf["decision_sla_days"] > 0
    assert wf["revision_sla_days"] > 0

    # Duplicate slug returns 409 Conflict
    dup = client.post(
        "/api/v1/journals",
        headers=admin_headers,
        json={"title": "Another Title", "slug": "journal-software-analysis"},
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "journal_slug_already_exists"

    # Admin updates APC settings, DOI prefix, and deactivates the journal
    updated = client.patch(
        f"/api/v1/journals/{created['id']}",
        headers=admin_headers,
        json={
            "apc_enabled": False,
            "apc_amount_cents": 0,
            "apc_currency": "EUR",
            "doi_prefix": "10.7777",
            "is_active": False,
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["apc_enabled"] is False
    assert body["apc_amount_cents"] == 0
    assert body["apc_currency"] == "EUR"
    assert body["doi_prefix"] == "10.7777"
    assert body["is_active"] is False


def test_public_directory_lists_only_active_journals_and_exposes_metadata(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    j1 = _create_journal(client, admin_headers, title="AI Systems Review", slug="ai-systems")
    j2 = _create_journal(client, admin_headers, title="Bioinformatics Today", slug="bio-today")
    j3 = _create_journal(client, admin_headers, title="Archived Journal", slug="archived-j")

    # Deactivate j3
    deact = client.patch(
        f"/api/v1/journals/{j3['id']}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert deact.status_code == 200

    # Unauthenticated visitor browses paginated active directory
    page1 = client.get("/api/v1/journals?page=1&page_size=1")
    assert page1.status_code == 200
    body1 = page1.json()
    assert body1["page"] == 1
    assert body1["page_size"] == 1
    assert body1["total"] == 2
    assert len(body1["items"]) == 1
    assert body1["items"][0]["id"] == j1["id"]
    assert body1["items"][0]["workflow_config"]["anonymity_mode"] == "double_anonymous"

    # Search filter works publicly
    search = client.get("/api/v1/journals?search=bioinformatics")
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["items"][0]["id"] == j2["id"]

    # Inspect individual journal publicly
    detail = client.get(f"/api/v1/journals/{j1['id']}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "AI Systems Review"
    assert detail.json()["workflow_config"]["min_reviewers"] == 2

    # Nonexistent journal returns 404 structured error
    missing = client.get("/api/v1/journals/999999")
    assert missing.status_code == 404
    assert missing.json()["code"] == "journal_not_found"


def test_non_admin_cannot_create_update_or_deactivate_journals(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(client, admin_headers, slug="protected-journal")
    chief = register_user(email="chief@university.edu", password="Password123!")
    chief_headers = auth_headers_for(email="chief@university.edu", password="Password123!")

    # Even assigning the user as Chief Editor does NOT grant journal create/update/deactivate rights
    assign = client.post(
        f"/api/v1/journals/{journal['id']}/members",
        headers=admin_headers,
        json={"user_id": chief["id"], "role": "chief_editor"},
    )
    assert assign.status_code == 201

    create_attempt = client.post(
        "/api/v1/journals",
        headers=chief_headers,
        json={"title": "Rogue Journal", "slug": "rogue-journal"},
    )
    assert create_attempt.status_code == 403
    assert create_attempt.json()["code"] == "admin_required"

    update_attempt = client.patch(
        f"/api/v1/journals/{journal['id']}",
        headers=chief_headers,
        json={"apc_enabled": True, "is_active": False},
    )
    assert update_attempt.status_code == 403
    assert update_attempt.json()["code"] == "admin_required"


def test_chief_editor_rbac_management_and_cross_journal_isolation(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal_a = _create_journal(client, admin_headers, title="Journal A", slug="journal-a")
    journal_b = _create_journal(client, admin_headers, title="Journal B", slug="journal-b")

    chief_a = register_user(email="chief.a@university.edu", password="Password123!")
    editor_a = register_user(email="editor.a@university.edu", password="Password123!")
    reviewer_b = register_user(email="reviewer.b@university.edu", password="Password123!")

    chief_a_headers = auth_headers_for(email="chief.a@university.edu", password="Password123!")

    # System Admin assigns chief_a as Chief Editor in Journal A ONLY
    m_chief_a = client.post(
        f"/api/v1/journals/{journal_a['id']}/members",
        headers=admin_headers,
        json={"user_id": chief_a["id"], "role": "chief_editor"},
    )
    assert m_chief_a.status_code == 201

    # System Admin assigns reviewer_b in Journal B
    m_rev_b = client.post(
        f"/api/v1/journals/{journal_b['id']}/members",
        headers=admin_headers,
        json={"user_id": reviewer_b["id"], "role": "reviewer"},
    )
    assert m_rev_b.status_code == 201
    membership_b_id = m_rev_b.json()["id"]

    # Chief Editor of Journal A can assign multiple roles in Journal A
    m_he = client.post(
        f"/api/v1/journals/{journal_a['id']}/members",
        headers=chief_a_headers,
        json={"user_id": editor_a["id"], "role": "handling_editor"},
    )
    assert m_he.status_code == 201
    assert m_he.json()["user"]["email"] == "editor.a@university.edu"

    m_author = client.post(
        f"/api/v1/journals/{journal_a['id']}/members",
        headers=chief_a_headers,
        json={"user_id": editor_a["id"], "role": "author"},
    )
    assert m_author.status_code == 201

    # Duplicate role assignment returns 409 Conflict
    dup_role = client.post(
        f"/api/v1/journals/{journal_a['id']}/members",
        headers=chief_a_headers,
        json={"user_id": editor_a["id"], "role": "handling_editor"},
    )
    assert dup_role.status_code == 409
    assert dup_role.json()["code"] == "membership_already_exists"

    # List Journal A members filtered by role
    filtered = client.get(
        f"/api/v1/journals/{journal_a['id']}/members?role=handling_editor",
        headers=chief_a_headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["user_id"] == editor_a["id"]

    # Cross-journal isolation: Chief Editor of Journal A has NO permissions in Journal B
    assert (
        client.get(
            f"/api/v1/journals/{journal_b['id']}/members",
            headers=chief_a_headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/journals/{journal_b['id']}/members",
            headers=chief_a_headers,
            json={"user_id": editor_a["id"], "role": "reviewer"},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/v1/journals/{journal_b['id']}/members/{membership_b_id}",
            headers=chief_a_headers,
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/journals/{journal_b['id']}/workflow-config",
            headers=chief_a_headers,
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/journals/{journal_b['id']}/workflow-config",
            headers=chief_a_headers,
            json={"min_reviewers": 3},
        ).status_code
        == 403
    )
    # Attempting to delete Journal B's membership through Journal A's endpoint returns 404
    assert (
        client.delete(
            f"/api/v1/journals/{journal_a['id']}/members/{membership_b_id}",
            headers=chief_a_headers,
        ).status_code
        == 404
    )

    # Chief Editor of Journal A can revoke a membership in Journal A
    revoke = client.delete(
        f"/api/v1/journals/{journal_a['id']}/members/{m_he.json()['id']}",
        headers=chief_a_headers,
    )
    assert revoke.status_code == 204

    after_revoke = client.get(
        f"/api/v1/journals/{journal_a['id']}/members?role=handling_editor",
        headers=chief_a_headers,
    )
    assert after_revoke.status_code == 200
    assert after_revoke.json()["total"] == 0

    # Once System Admin revokes chief_a's Chief Editor role, chief_a loses access to Journal A
    revoke_chief = client.delete(
        f"/api/v1/journals/{journal_a['id']}/members/{m_chief_a.json()['id']}",
        headers=admin_headers,
    )
    assert revoke_chief.status_code == 204

    lost_access = client.get(
        f"/api/v1/journals/{journal_a['id']}/workflow-config",
        headers=chief_a_headers,
    )
    assert lost_access.status_code == 403
    assert lost_access.json()["code"] == "journal_role_required"


def test_workflow_config_update_validation_and_role_restrictions(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(client, admin_headers, slug="wf-journal")
    chief = register_user(email="wf.chief@university.edu", password="Password123!")
    handling = register_user(email="wf.handling@university.edu", password="Password123!")

    chief_headers = auth_headers_for(email="wf.chief@university.edu", password="Password123!")
    handling_headers = auth_headers_for(
        email="wf.handling@university.edu",
        password="Password123!",
    )

    client.post(
        f"/api/v1/journals/{journal['id']}/members",
        headers=admin_headers,
        json={"user_id": chief["id"], "role": "chief_editor"},
    )
    client.post(
        f"/api/v1/journals/{journal['id']}/members",
        headers=admin_headers,
        json={"user_id": handling["id"], "role": "handling_editor"},
    )

    # Handling editor is NOT allowed to view/update workflow-config management endpoint
    assert (
        client.get(
            f"/api/v1/journals/{journal['id']}/workflow-config",
            headers=handling_headers,
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/journals/{journal['id']}/workflow-config",
            headers=handling_headers,
            json={"min_reviewers": 3},
        ).status_code
        == 403
    )

    # Chief Editor can view and update workflow config
    get_res = client.get(
        f"/api/v1/journals/{journal['id']}/workflow-config",
        headers=chief_headers,
    )
    assert get_res.status_code == 200
    assert get_res.json()["anonymity_mode"] == "double_anonymous"

    patch_res = client.patch(
        f"/api/v1/journals/{journal['id']}/workflow-config",
        headers=chief_headers,
        json={
            "anonymity_mode": "single_anonymous",
            "min_reviewers": 3,
            "require_desk_review": False,
            "require_plagiarism_check": True,
            "desk_review_sla_days": 5,
            "review_sla_days": 14,
            "decision_sla_days": 10,
            "revision_sla_days": 20,
        },
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["anonymity_mode"] == "single_anonymous"
    assert updated["min_reviewers"] == 3
    assert updated["require_desk_review"] is False
    assert updated["require_plagiarism_check"] is True
    assert updated["desk_review_sla_days"] == 5
    assert updated["review_sla_days"] == 14
    assert updated["decision_sla_days"] == 10
    assert updated["revision_sla_days"] == 20

    # Invalid values return 422 with structured error envelope
    bad_mode = client.patch(
        f"/api/v1/journals/{journal['id']}/workflow-config",
        headers=chief_headers,
        json={"anonymity_mode": "triple_blind"},
    )
    assert bad_mode.status_code == 422
    assert bad_mode.json()["code"] == "validation_error"

    bad_min_reviewers = client.patch(
        f"/api/v1/journals/{journal['id']}/workflow-config",
        headers=chief_headers,
        json={"min_reviewers": 0},
    )
    assert bad_min_reviewers.status_code == 422
    assert bad_min_reviewers.json()["code"] == "validation_error"

    bad_sla = client.patch(
        f"/api/v1/journals/{journal['id']}/workflow-config",
        headers=chief_headers,
        json={"review_sla_days": 0},
    )
    assert bad_sla.status_code == 422
    assert bad_sla.json()["code"] == "validation_error"

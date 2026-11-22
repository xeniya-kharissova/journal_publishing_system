"""Smoke and idempotency tests for the demo seed script and seeded API workflows."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.storage import StorageAdapter
from scripts.seed_demo import DEMO_PASSWORD, seed_demo_data


def _login_headers(client: TestClient, email: str) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": DEMO_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_seed_demo_is_idempotent_and_populates_all_stages(
    db_session: Session,
    storage_adapter: StorageAdapter,
) -> None:
    first = seed_demo_data(db_session, storage_adapter)
    second = seed_demo_data(db_session, storage_adapter)

    assert first == second
    assert first.users == 10
    assert first.journals == 2
    assert first.memberships == 10
    assert first.manuscripts == 5
    assert first.versions == 5
    assert first.invitations == 5
    assert first.reviews == 4
    assert first.decisions == 2


def test_seeded_demo_users_authenticate_and_use_core_endpoints(
    client: TestClient,
    db_session: Session,
    storage_adapter: StorageAdapter,
) -> None:
    seed_demo_data(db_session, storage_adapter)

    # Public journal directory shows both seeded journals with distinct workflow configs
    journals_resp = client.get("/api/v1/journals")
    assert journals_resp.status_code == 200
    journals = {j["slug"]: j for j in journals_resp.json()["items"]}
    assert set(journals.keys()) == {"jcs-research", "open-bio-data"}
    assert journals["jcs-research"]["workflow_config"]["anonymity_mode"] == "double_anonymous"
    assert journals["open-bio-data"]["workflow_config"]["anonymity_mode"] == "open"

    # Authenticate key seeded roles
    admin_headers = _login_headers(client, "admin@journal-platform.org")
    chief_headers = _login_headers(client, "chief.cs@journal-platform.org")
    editor_headers = _login_headers(client, "editor.cs@journal-platform.org")
    reviewer1_headers = _login_headers(client, "reviewer1@uni-alpha.edu")
    author1_headers = _login_headers(client, "author1@uni-delta.edu")
    author2_headers = _login_headers(client, "author2@uni-epsilon.edu")

    # Admin inspects platform users
    users_resp = client.get("/api/v1/admin/users", headers=admin_headers)
    assert users_resp.status_code == 200
    assert users_resp.json()["total"] == 10

    # Chief Editor views full editorial queue (excludes drafts)
    queue_resp = client.get(
        f"/api/v1/journals/{journals['jcs-research']['id']}/manuscripts",
        headers=chief_headers,
    )
    assert queue_resp.status_code == 200
    assert queue_resp.json()["total"] == 3

    # Handling Editor views only manuscripts assigned to themselves
    he_queue_resp = client.get(
        f"/api/v1/journals/{journals['jcs-research']['id']}/manuscripts",
        headers=editor_headers,
    )
    assert he_queue_resp.status_code == 200
    assert he_queue_resp.json()["total"] == 2
    assert {m["status"] for m in he_queue_resp.json()["items"]} == {
        "under_review",
        "revision_requested",
    }

    # Author 1 sees all 4 of their manuscripts across stages
    my_ms_resp = client.get("/api/v1/manuscripts", headers=author1_headers)
    assert my_ms_resp.status_code == 200
    ms_by_status = {m["status"]: m for m in my_ms_resp.json()["items"]}
    assert set(ms_by_status.keys()) == {"draft", "submitted", "under_review", "revision_requested"}

    # Reviewer 1 accesses double-anonymous under_review manuscript (masked) and downloads PDF
    ur_id = ms_by_status["under_review"]["id"]
    ms_for_rev = client.get(f"/api/v1/manuscripts/{ur_id}", headers=reviewer1_headers)
    assert ms_for_rev.status_code == 200
    assert ms_for_rev.json()["submitter_id"] is None
    assert ms_for_rev.json()["co_authors"] == []

    pdf_resp = client.get(
        f"/api/v1/manuscripts/{ur_id}/versions/1/download",
        headers=reviewer1_headers,
    )
    assert pdf_resp.status_code == 200
    assert pdf_resp.content.startswith(b"%PDF-")

    # Author does not see reviews for undecided under_review round yet
    ur_author_reviews = client.get(f"/api/v1/manuscripts/{ur_id}/reviews", headers=author1_headers)
    assert ur_author_reviews.status_code == 200
    assert ur_author_reviews.json() == []

    # Handling Editor sees unmasked reviews + confidential comments; Author sees masked reviews for decided round
    rev_id = ms_by_status["revision_requested"]["id"]
    editor_reviews = client.get(f"/api/v1/manuscripts/{rev_id}/reviews", headers=editor_headers)
    assert editor_reviews.status_code == 200
    assert len(editor_reviews.json()) == 2
    assert editor_reviews.json()[0]["confidential_comments_to_editor"] is not None

    author_reviews = client.get(f"/api/v1/manuscripts/{rev_id}/reviews", headers=author1_headers)
    assert author_reviews.status_code == 200
    assert all(r["reviewer_id"] is None for r in author_reviews.json())
    assert all(r["confidential_comments_to_editor"] is None for r in author_reviews.json())

    # Author 1 views round-1 major_revision decision
    decisions_resp = client.get(f"/api/v1/manuscripts/{rev_id}/decisions", headers=author1_headers)
    assert decisions_resp.status_code == 200
    assert decisions_resp.json()[0]["decision"] == "major_revision"

    # Author 2 views accepted manuscript in open-bio-data
    author2_ms = client.get("/api/v1/manuscripts", headers=author2_headers)
    assert author2_ms.status_code == 200
    assert author2_ms.json()["items"][0]["status"] == "accepted"

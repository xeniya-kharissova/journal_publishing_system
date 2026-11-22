"""HTTP API tests for editorial workflow state machine, audit history, editor assignment, and desk review."""

import io
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy.orm import Session

from app.models.manuscript import Manuscript, ManuscriptStatus


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _create_journal(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    title: str = "Journal of Empirical Computing",
    slug: str = "empirical-computing",
) -> dict[str, Any]:
    resp = client.post(
        "/api/v1/journals",
        headers=admin_headers,
        json={"title": title, "slug": slug},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _assign_role(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    journal_id: int,
    user_id: int,
    role: str,
) -> None:
    resp = client.post(
        f"/api/v1/journals/{journal_id}/members",
        headers=admin_headers,
        json={"user_id": user_id, "role": role},
    )
    assert resp.status_code == 201, resp.text


def _create_draft(
    client: TestClient,
    author_headers: dict[str, str],
    *,
    journal_id: int,
    title: str = "Workflow Verification Paper",
    upload_pdf: bool = True,
) -> dict[str, Any]:
    resp = client.post(
        "/api/v1/manuscripts",
        headers=author_headers,
        json={
            "journal_id": journal_id,
            "title": title,
            "abstract": "Testing the editorial state machine and desk review workflow.",
        },
    )
    assert resp.status_code == 201, resp.text
    manuscript = resp.json()
    if upload_pdf:
        up = client.post(
            f"/api/v1/manuscripts/{manuscript['id']}/versions",
            headers=author_headers,
            files={"file": ("paper_v1.pdf", _blank_pdf(), "application/pdf")},
        )
        assert up.status_code == 201, up.text
    return manuscript


def test_submit_requires_uploaded_pdf_and_records_audit_history(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(client, admin_headers)
    author = register_user(email="submitter@uni.edu")
    other = register_user(email="other.user@uni.edu")
    author_headers = auth_headers_for(email=author["email"])
    other_headers = auth_headers_for(email=other["email"])

    draft = _create_draft(client, author_headers, journal_id=journal["id"], upload_pdf=False)
    ms_id = draft["id"]

    # Another user cannot submit someone else's draft
    forbidden = client.post(f"/api/v1/manuscripts/{ms_id}/submit", headers=other_headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "manuscript_submit_forbidden"

    # Submitting without an uploaded PDF is rejected with 400
    no_pdf = client.post(f"/api/v1/manuscripts/{ms_id}/submit", headers=author_headers)
    assert no_pdf.status_code == 400
    assert no_pdf.json()["code"] == "manuscript_version_required"

    # Upload v1 and submit
    up = client.post(
        f"/api/v1/manuscripts/{ms_id}/versions",
        headers=author_headers,
        files={"file": ("submission_v1.pdf", _blank_pdf(), "application/pdf")},
    )
    assert up.status_code == 201

    submitted = client.post(
        f"/api/v1/manuscripts/{ms_id}/submit",
        headers=author_headers,
        json={"note": "Ready for editorial screening."},
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["status"] == "submitted"
    assert body["submitted_at"] is not None
    assert body["stage_entered_at"] is not None

    # Re-submitting an already submitted manuscript returns 409 Conflict
    duplicate_submit = client.post(f"/api/v1/manuscripts/{ms_id}/submit", headers=author_headers)
    assert duplicate_submit.status_code == 409
    assert duplicate_submit.json()["code"] == "invalid_status_transition"

    # Status history contains the immutable transition entry
    history = client.get(f"/api/v1/manuscripts/{ms_id}/status-history", headers=author_headers)
    assert history.status_code == 200
    entries = history.json()
    assert len(entries) == 1
    assert entries[0]["from_status"] == "draft"
    assert entries[0]["to_status"] == "submitted"
    assert entries[0]["changed_by_id"] == author["id"]
    assert entries[0]["note"] == "Ready for editorial screening."

    # Unauthorized user cannot read status history
    unauth_hist = client.get(f"/api/v1/manuscripts/{ms_id}/status-history", headers=other_headers)
    assert unauth_hist.status_code == 403


def test_author_withdrawal_permissions_and_terminal_state_protection(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
    db_session: Session,
) -> None:
    journal = _create_journal(client, admin_headers)
    author = register_user(email="withdraw.author@uni.edu")
    other = register_user(email="stranger@uni.edu")
    author_headers = auth_headers_for(email=author["email"])
    other_headers = auth_headers_for(email=other["email"])

    draft = _create_draft(client, author_headers, journal_id=journal["id"], upload_pdf=True)
    ms_id = draft["id"]
    assert client.post(f"/api/v1/manuscripts/{ms_id}/submit", headers=author_headers).status_code == 200

    # Other author cannot withdraw
    denied = client.post(f"/api/v1/manuscripts/{ms_id}/withdraw", headers=other_headers)
    assert denied.status_code == 403
    assert denied.json()["code"] == "manuscript_withdraw_forbidden"

    # Submitting author withdraws successfully
    withdrawn = client.post(
        f"/api/v1/manuscripts/{ms_id}/withdraw",
        headers=author_headers,
        json={"note": "Submitting to a special issue instead."},
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "withdrawn"

    # Terminal state accepts no further transitions (409 Conflict)
    again = client.post(f"/api/v1/manuscripts/{ms_id}/withdraw", headers=author_headers)
    assert again.status_code == 409
    assert again.json()["code"] == "invalid_status_transition"

    # Published manuscript cannot be withdrawn (409 Conflict)
    pub_draft = _create_draft(client, author_headers, journal_id=journal["id"], title="Published Paper")
    pub_row = db_session.get(Manuscript, pub_draft["id"])
    assert pub_row is not None
    pub_row.status = ManuscriptStatus.PUBLISHED.value
    db_session.commit()

    pub_withdraw = client.post(
        f"/api/v1/manuscripts/{pub_draft['id']}/withdraw",
        headers=author_headers,
    )
    assert pub_withdraw.status_code == 409
    assert pub_withdraw.json()["code"] == "invalid_status_transition"


def test_editorial_queue_editor_assignment_and_cross_journal_isolation(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    j1 = _create_journal(client, admin_headers, title="Journal Alpha", slug="journal-alpha")
    j2 = _create_journal(client, admin_headers, title="Journal Beta", slug="journal-beta")

    author = register_user(email="queue.author@uni.edu")
    chief_j1 = register_user(email="chief.alpha@uni.edu")
    chief_j2 = register_user(email="chief.beta@uni.edu")
    editor_j1 = register_user(email="editor.alpha@uni.edu")
    editor_j2 = register_user(email="editor.beta@uni.edu")
    plain_reviewer = register_user(email="reviewer.alpha@uni.edu")

    _assign_role(client, admin_headers, journal_id=j1["id"], user_id=chief_j1["id"], role="chief_editor")
    _assign_role(client, admin_headers, journal_id=j2["id"], user_id=chief_j2["id"], role="chief_editor")
    _assign_role(client, admin_headers, journal_id=j1["id"], user_id=editor_j1["id"], role="handling_editor")
    _assign_role(client, admin_headers, journal_id=j2["id"], user_id=editor_j2["id"], role="handling_editor")
    _assign_role(client, admin_headers, journal_id=j1["id"], user_id=plain_reviewer["id"], role="reviewer")

    author_headers = auth_headers_for(email=author["email"])
    chief_j1_headers = auth_headers_for(email=chief_j1["email"])
    chief_j2_headers = auth_headers_for(email=chief_j2["email"])

    # Create one unsubmitted draft and one submitted manuscript in Journal 1
    _create_draft(client, author_headers, journal_id=j1["id"], title="Private Draft")
    submitted_ms = _create_draft(client, author_headers, journal_id=j1["id"], title="Submitted Paper")
    assert (
        client.post(f"/api/v1/manuscripts/{submitted_ms['id']}/submit", headers=author_headers).status_code
        == 200
    )

    # Journal 1 Chief Editor sees only non-draft submissions in the queue
    queue = client.get(f"/api/v1/journals/{j1['id']}/manuscripts?status=submitted", headers=chief_j1_headers)
    assert queue.status_code == 200
    assert queue.json()["total"] == 1
    assert queue.json()["items"][0]["id"] == submitted_ms["id"]

    # Journal 2 Chief Editor cannot view Journal 1 queue or assign editors in Journal 1
    cross_queue = client.get(f"/api/v1/journals/{j1['id']}/manuscripts", headers=chief_j2_headers)
    assert cross_queue.status_code == 403

    cross_assign = client.post(
        f"/api/v1/manuscripts/{submitted_ms['id']}/assign-editor",
        headers=chief_j2_headers,
        json={"editor_id": editor_j1["id"]},
    )
    assert cross_assign.status_code == 403

    # Assigning a reviewer (not an editor) or an editor from Journal 2 is rejected
    bad_role = client.post(
        f"/api/v1/manuscripts/{submitted_ms['id']}/assign-editor",
        headers=chief_j1_headers,
        json={"editor_id": plain_reviewer["id"]},
    )
    assert bad_role.status_code == 400
    assert bad_role.json()["code"] == "invalid_handling_editor"

    wrong_journal_editor = client.post(
        f"/api/v1/manuscripts/{submitted_ms['id']}/assign-editor",
        headers=chief_j1_headers,
        json={"editor_id": editor_j2["id"]},
    )
    assert wrong_journal_editor.status_code == 400
    assert wrong_journal_editor.json()["code"] == "invalid_handling_editor"

    # Valid assignment of Journal 1 Handling Editor succeeds
    assigned = client.post(
        f"/api/v1/manuscripts/{submitted_ms['id']}/assign-editor",
        headers=chief_j1_headers,
        json={"editor_id": editor_j1["id"]},
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned_editor_id"] == editor_j1["id"]


def test_desk_review_advance_and_desk_reject_paths_and_config_override(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(client, admin_headers, slug="desk-review-journal")
    author = register_user(email="desk.author@uni.edu")
    chief = register_user(email="desk.chief@uni.edu")
    assigned_ed = register_user(email="desk.assigned@uni.edu")
    unassigned_ed = register_user(email="desk.unassigned@uni.edu")

    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=chief["id"], role="chief_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=assigned_ed["id"], role="handling_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=unassigned_ed["id"], role="handling_editor")

    author_headers = auth_headers_for(email=author["email"])
    chief_headers = auth_headers_for(email=chief["email"])
    assigned_headers = auth_headers_for(email=assigned_ed["email"])
    unassigned_headers = auth_headers_for(email=unassigned_ed["email"])

    # Paper 1: full path submitted -> desk_review -> under_review
    p1 = _create_draft(client, author_headers, journal_id=journal["id"], title="Paper 1 Advance")
    assert client.post(f"/api/v1/manuscripts/{p1['id']}/submit", headers=author_headers).status_code == 200
    assert (
        client.post(
            f"/api/v1/manuscripts/{p1['id']}/assign-editor",
            headers=chief_headers,
            json={"editor_id": assigned_ed["id"]},
        ).status_code
        == 200
    )

    # Unassigned handling editor gets 403 on desk review actions
    assert (
        client.post(f"/api/v1/manuscripts/{p1['id']}/desk-review", headers=unassigned_headers).status_code
        == 403
    )

    # With require_desk_review=True (default), skipping directly submitted -> under_review returns 409
    skip_blocked = client.post(
        f"/api/v1/manuscripts/{p1['id']}/advance-to-review",
        headers=assigned_headers,
    )
    assert skip_blocked.status_code == 409
    assert skip_blocked.json()["code"] == "invalid_status_transition"

    # Assigned Handling Editor moves submitted -> desk_review -> under_review
    in_desk = client.post(
        f"/api/v1/manuscripts/{p1['id']}/desk-review",
        headers=assigned_headers,
        json={"note": "Checking scope and formatting."},
    )
    assert in_desk.status_code == 200
    assert in_desk.json()["status"] == "desk_review"

    in_review = client.post(
        f"/api/v1/manuscripts/{p1['id']}/advance-to-review",
        headers=assigned_headers,
        json={"note": "Passed desk screening; inviting reviewers."},
    )
    assert in_review.status_code == 200
    assert in_review.json()["status"] == "under_review"
    assert in_review.json()["current_review_round"] == 1

    # Verify full 3-step audit trail
    history = client.get(f"/api/v1/manuscripts/{p1['id']}/status-history", headers=assigned_headers)
    assert history.status_code == 200
    transitions = [(e["from_status"], e["to_status"]) for e in history.json()]
    assert transitions == [
        ("draft", "submitted"),
        ("submitted", "desk_review"),
        ("desk_review", "under_review"),
    ]

    # Paper 2: desk rejection path (submitted -> desk_review -> rejected)
    p2 = _create_draft(client, author_headers, journal_id=journal["id"], title="Paper 2 Out of Scope")
    assert client.post(f"/api/v1/manuscripts/{p2['id']}/submit", headers=author_headers).status_code == 200
    assert (
        client.post(
            f"/api/v1/manuscripts/{p2['id']}/assign-editor",
            headers=chief_headers,
            json={"editor_id": assigned_ed["id"]},
        ).status_code
        == 200
    )

    # Cannot desk-reject directly from submitted without entering desk_review
    premature_reject = client.post(
        f"/api/v1/manuscripts/{p2['id']}/desk-reject",
        headers=assigned_headers,
        json={"rationale": "Out of scope."},
    )
    assert premature_reject.status_code == 409

    assert client.post(f"/api/v1/manuscripts/{p2['id']}/desk-review", headers=assigned_headers).status_code == 200
    rejected = client.post(
        f"/api/v1/manuscripts/{p2['id']}/desk-reject",
        headers=assigned_headers,
        json={"rationale": "Submission falls outside the journal's empirical computing scope."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["decided_at"] is not None

    # Terminal rejected state cannot transition further
    assert (
        client.post(f"/api/v1/manuscripts/{p2['id']}/advance-to-review", headers=assigned_headers).status_code
        == 409
    )

    # Paper 3: when require_desk_review=False, submitted -> under_review is allowed directly
    cfg_update = client.patch(
        f"/api/v1/journals/{journal['id']}/workflow-config",
        headers=chief_headers,
        json={"require_desk_review": False},
    )
    assert cfg_update.status_code == 200
    assert cfg_update.json()["require_desk_review"] is False

    p3 = _create_draft(client, author_headers, journal_id=journal["id"], title="Paper 3 Direct Review")
    assert client.post(f"/api/v1/manuscripts/{p3['id']}/submit", headers=author_headers).status_code == 200
    direct_review = client.post(
        f"/api/v1/manuscripts/{p3['id']}/advance-to-review",
        headers=chief_headers,
        json={"note": "Desk review disabled by journal policy."},
    )
    assert direct_review.status_code == 200
    assert direct_review.json()["status"] == "under_review"
    assert direct_review.json()["current_review_round"] == 1

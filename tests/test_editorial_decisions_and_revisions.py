"""HTTP API tests for editorial decisions, quality gates, Chief Editor overrides, and revision rounds."""

import io
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from pypdf import PdfWriter


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
    title: str = "Journal of Peer-Reviewed Systems",
    slug: str = "peer-reviewed-systems",
    min_reviewers: int = 2,
) -> dict[str, Any]:
    resp = client.post(
        "/api/v1/journals",
        headers=admin_headers,
        json={"title": title, "slug": slug},
    )
    assert resp.status_code == 201, resp.text
    journal = resp.json()
    if min_reviewers != 2:
        cfg = client.patch(
            f"/api/v1/journals/{journal['id']}/workflow-config",
            headers=admin_headers,
            json={"min_reviewers": min_reviewers},
        )
        assert cfg.status_code == 200, cfg.text
    return journal


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


def _setup_under_review_manuscript(
    client: TestClient,
    *,
    journal_id: int,
    author_headers: dict[str, str],
    chief_headers: dict[str, str],
    editor_id: int,
    editor_headers: dict[str, str],
) -> dict[str, Any]:
    draft = client.post(
        "/api/v1/manuscripts",
        headers=author_headers,
        json={
            "journal_id": journal_id,
            "title": "Multi-Round Revision Study",
            "abstract": "Investigating iterative scholarly peer-review improvements.",
            "keywords": ["peer-review", "revisions"],
        },
    )
    assert draft.status_code == 201, draft.text
    ms_id = draft.json()["id"]

    upload = client.post(
        f"/api/v1/manuscripts/{ms_id}/versions",
        headers=author_headers,
        files={"file": ("study_v1.pdf", _blank_pdf(), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text

    assert client.post(f"/api/v1/manuscripts/{ms_id}/submit", headers=author_headers).status_code == 200
    assert (
        client.post(
            f"/api/v1/manuscripts/{ms_id}/assign-editor",
            headers=chief_headers,
            json={"editor_id": editor_id},
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/manuscripts/{ms_id}/desk-review", headers=editor_headers).status_code == 200
    under_review = client.post(
        f"/api/v1/manuscripts/{ms_id}/advance-to-review",
        headers=editor_headers,
    )
    assert under_review.status_code == 200, under_review.text
    return under_review.json()


def _complete_review(
    client: TestClient,
    *,
    manuscript_id: int,
    editor_headers: dict[str, str],
    reviewer_id: int,
    reviewer_headers: dict[str, str],
    recommendation: str = "accept",
    comments_to_author: str = "Thorough work.",
    confidential_comments: str | None = "Confidential editor note.",
) -> dict[str, Any]:
    inv = client.post(
        f"/api/v1/manuscripts/{manuscript_id}/invitations",
        headers=editor_headers,
        json={"reviewer_id": reviewer_id},
    )
    assert inv.status_code == 201, inv.text
    inv_id = inv.json()["id"]

    assert client.post(f"/api/v1/review-invitations/{inv_id}/accept", headers=reviewer_headers).status_code == 200

    rev = client.post(
        f"/api/v1/review-invitations/{inv_id}/review",
        headers=reviewer_headers,
        json={
            "originality_score": 4,
            "methodology_score": 5,
            "clarity_score": 4,
            "significance_score": 5,
            "recommendation": recommendation,
            "comments_to_author": comments_to_author,
            "confidential_comments_to_editor": confidential_comments,
        },
    )
    assert rev.status_code == 201, rev.text
    return rev.json()


def test_full_multi_round_revision_cycle_and_author_feedback_visibility(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(client, admin_headers, slug="multi-round", min_reviewers=2)
    chief = register_user(email="chief.mr@uni.edu")
    editor = register_user(email="editor.mr@uni.edu")
    author = register_user(email="author.mr@uni.edu")
    rev1 = register_user(email="rev1.mr@uni.edu", full_name="Prof. Hidden One")
    rev2 = register_user(email="rev2.mr@uni.edu", full_name="Dr. Hidden Two")
    outsider = register_user(email="outsider.mr@uni.edu")

    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=chief["id"], role="chief_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=editor["id"], role="handling_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=rev1["id"], role="reviewer")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=rev2["id"], role="reviewer")

    chief_headers = auth_headers_for(email=chief["email"])
    editor_headers = auth_headers_for(email=editor["email"])
    author_headers = auth_headers_for(email=author["email"])
    rev1_headers = auth_headers_for(email=rev1["email"])
    rev2_headers = auth_headers_for(email=rev2["email"])
    outsider_headers = auth_headers_for(email=outsider["email"])

    ms = _setup_under_review_manuscript(
        client,
        journal_id=journal["id"],
        author_headers=author_headers,
        chief_headers=chief_headers,
        editor_id=editor["id"],
        editor_headers=editor_headers,
    )
    ms_id = ms["id"]
    assert ms["current_version_number"] == 1
    assert ms["current_review_round"] == 1

    # Round 1: two reviewers submit evaluations
    _complete_review(
        client,
        manuscript_id=ms_id,
        editor_headers=editor_headers,
        reviewer_id=rev1["id"],
        reviewer_headers=rev1_headers,
        recommendation="major_revision",
        comments_to_author="Please add ablation experiments in section 4.",
        confidential_comments="ROUND1_SECRET_NOTE_1",
    )
    _complete_review(
        client,
        manuscript_id=ms_id,
        editor_headers=editor_headers,
        reviewer_id=rev2["id"],
        reviewer_headers=rev2_headers,
        recommendation="minor_revision",
        comments_to_author="Clarify notation in Table 1.",
        confidential_comments="ROUND1_SECRET_NOTE_2",
    )

    # Assigned Handling Editor issues major_revision decision for round 1
    dec1 = client.post(
        f"/api/v1/manuscripts/{ms_id}/decisions",
        headers=editor_headers,
        json={
            "decision": "major_revision",
            "decision_letter": "Please address both reviewers' comments and submit a revised PDF.",
        },
    )
    assert dec1.status_code == 201, dec1.text
    dec1_data = dec1.json()
    assert dec1_data["review_round"] == 1
    assert dec1_data["manuscript_version_number"] == 1
    assert dec1_data["decision"] == "major_revision"
    assert dec1_data["override_reason"] is None

    # Manuscript transitioned to revision_requested with decided_at recorded
    ms_after_dec1 = client.get(f"/api/v1/manuscripts/{ms_id}", headers=author_headers).json()
    assert ms_after_dec1["status"] == "revision_requested"
    assert ms_after_dec1["decided_at"] is not None

    # Submitting author can view decision record and anonymized round-1 feedback
    author_decisions = client.get(f"/api/v1/manuscripts/{ms_id}/decisions", headers=author_headers)
    assert author_decisions.status_code == 200
    assert len(author_decisions.json()) == 1
    assert author_decisions.json()[0]["decision_letter"] == dec1_data["decision_letter"]

    author_r1_reviews = client.get(
        f"/api/v1/manuscripts/{ms_id}/reviews",
        params={"review_round": 1},
        headers=author_headers,
    )
    assert author_r1_reviews.status_code == 200
    assert len(author_r1_reviews.json()) == 2
    assert "ROUND1_SECRET_NOTE_1" not in author_r1_reviews.text
    assert "Prof. Hidden One" not in author_r1_reviews.text

    # Outsider cannot view decisions
    assert client.get(f"/api/v1/manuscripts/{ms_id}/decisions", headers=outsider_headers).status_code == 403

    # Attempting to resubmit WITHOUT uploading a newer PDF version is rejected (400)
    resubmit_without_v2 = client.post(
        f"/api/v1/manuscripts/{ms_id}/resubmit",
        headers=author_headers,
    )
    assert resubmit_without_v2.status_code == 400
    assert resubmit_without_v2.json()["code"] == "revised_version_required"

    # Another user cannot resubmit on behalf of the author
    assert client.post(f"/api/v1/manuscripts/{ms_id}/resubmit", headers=outsider_headers).status_code == 403

    # Author uploads v2 with response_to_reviewers letter (v1 remains immutable)
    upload_v2 = client.post(
        f"/api/v1/manuscripts/{ms_id}/versions",
        headers=author_headers,
        files={"file": ("study_v2.pdf", _blank_pdf(), "application/pdf")},
        data={"response_to_reviewers": "Added ablation experiments and clarified Table 1."},
    )
    assert upload_v2.status_code == 201, upload_v2.text
    assert upload_v2.json()["version_number"] == 2
    assert upload_v2.json()["response_to_reviewers"] == "Added ablation experiments and clarified Table 1."

    versions = client.get(f"/api/v1/manuscripts/{ms_id}/versions", headers=author_headers).json()
    assert [v["version_number"] for v in versions] == [1, 2]

    # Author formally resubmits -> revision_requested -> under_review, review_round incremented to 2
    resubmitted = client.post(
        f"/api/v1/manuscripts/{ms_id}/resubmit",
        headers=author_headers,
        json={"note": "Revised manuscript ready for round 2."},
    )
    assert resubmitted.status_code == 200, resubmitted.text
    assert resubmitted.json()["status"] == "under_review"
    assert resubmitted.json()["current_version_number"] == 2
    assert resubmitted.json()["current_review_round"] == 2

    # Round 2: both reviewers re-invited and submit accept reviews on v2
    r2_rev1 = _complete_review(
        client,
        manuscript_id=ms_id,
        editor_headers=editor_headers,
        reviewer_id=rev1["id"],
        reviewer_headers=rev1_headers,
        recommendation="accept",
        comments_to_author="All concerns addressed.",
    )
    r2_rev2 = _complete_review(
        client,
        manuscript_id=ms_id,
        editor_headers=editor_headers,
        reviewer_id=rev2["id"],
        reviewer_headers=rev2_headers,
        recommendation="accept",
        comments_to_author="Ready for publication.",
    )
    assert r2_rev1["review_round"] == 2
    assert r2_rev2["review_round"] == 2
    assert r2_rev1["manuscript_version_id"] == upload_v2.json()["id"]

    # Handling Editor now satisfies min_reviewers=2 for round 2 and accepts
    dec2 = client.post(
        f"/api/v1/manuscripts/{ms_id}/decisions",
        headers=editor_headers,
        json={
            "decision": "accept",
            "decision_letter": "Congratulations! Your manuscript is accepted for publication.",
        },
    )
    assert dec2.status_code == 201, dec2.text
    assert dec2.json()["review_round"] == 2
    assert dec2.json()["manuscript_version_number"] == 2
    assert dec2.json()["decision"] == "accept"

    ms_final = client.get(f"/api/v1/manuscripts/{ms_id}", headers=author_headers).json()
    assert ms_final["status"] == "accepted"

    # Audit history captures the entire multi-round lifecycle
    history = client.get(f"/api/v1/manuscripts/{ms_id}/status-history", headers=editor_headers).json()
    transitions = [(h["from_status"], h["to_status"]) for h in history]
    assert transitions == [
        ("draft", "submitted"),
        ("submitted", "desk_review"),
        ("desk_review", "under_review"),
        ("under_review", "revision_requested"),
        ("revision_requested", "under_review"),
        ("under_review", "accepted"),
    ]


def test_accept_quality_gate_blocking_and_chief_editor_override_auditing(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(client, admin_headers, slug="quality-gate", min_reviewers=2)
    chief = register_user(email="chief.qg@uni.edu")
    editor = register_user(email="editor.qg@uni.edu")
    author = register_user(email="author.qg@uni.edu")
    rev1 = register_user(email="rev1.qg@uni.edu")

    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=chief["id"], role="chief_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=editor["id"], role="handling_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=rev1["id"], role="reviewer")

    chief_headers = auth_headers_for(email=chief["email"])
    editor_headers = auth_headers_for(email=editor["email"])
    author_headers = auth_headers_for(email=author["email"])
    rev1_headers = auth_headers_for(email=rev1["email"])

    ms = _setup_under_review_manuscript(
        client,
        journal_id=journal["id"],
        author_headers=author_headers,
        chief_headers=chief_headers,
        editor_id=editor["id"],
        editor_headers=editor_headers,
    )
    ms_id = ms["id"]

    # Complete only 1 of 2 required reviews
    _complete_review(
        client,
        manuscript_id=ms_id,
        editor_headers=editor_headers,
        reviewer_id=rev1["id"],
        reviewer_headers=rev1_headers,
        recommendation="accept",
    )

    # Handling Editor cannot accept without meeting min_reviewers -> 409 Conflict
    blocked_he = client.post(
        f"/api/v1/manuscripts/{ms_id}/decisions",
        headers=editor_headers,
        json={
            "decision": "accept",
            "decision_letter": "Trying to accept with 1 review.",
        },
    )
    assert blocked_he.status_code == 409
    assert blocked_he.json()["code"] == "quality_gate_not_met"

    # Handling Editor cannot override quality gates even with override_reason -> 403 Forbidden
    forbidden_override = client.post(
        f"/api/v1/manuscripts/{ms_id}/decisions",
        headers=editor_headers,
        json={
            "decision": "accept",
            "decision_letter": "Attempting unauthorized override.",
            "override_reason": "Trying to bypass min_reviewers.",
        },
    )
    assert forbidden_override.status_code == 403
    assert forbidden_override.json()["code"] == "quality_gate_override_forbidden"

    # Chief Editor without override_reason is also blocked with 409 Conflict
    chief_no_reason = client.post(
        f"/api/v1/manuscripts/{ms_id}/decisions",
        headers=chief_headers,
        json={
            "decision": "accept",
            "decision_letter": "Accepting without override reason.",
        },
    )
    assert chief_no_reason.status_code == 409
    assert chief_no_reason.json()["code"] == "quality_gate_not_met"

    # Chief Editor with explicit non-empty override_reason succeeds and audits the override
    override_text = "Second reviewer withdrew late; editorial board unanimously approved acceptance."
    chief_override = client.post(
        f"/api/v1/manuscripts/{ms_id}/decisions",
        headers=chief_headers,
        json={
            "decision": "accept",
            "decision_letter": "Accepted via Chief Editor quality-gate override.",
            "override_reason": override_text,
        },
    )
    assert chief_override.status_code == 201, chief_override.text
    assert chief_override.json()["decision"] == "accept"
    assert chief_override.json()["override_reason"] == override_text

    # Status history entry includes the override justification
    history = client.get(f"/api/v1/manuscripts/{ms_id}/status-history", headers=chief_headers).json()
    last_entry = history[-1]
    assert last_entry["from_status"] == "under_review"
    assert last_entry["to_status"] == "accepted"
    assert override_text in (last_entry["note"] or "")


def test_reject_decision_and_invalid_state_guards(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(client, admin_headers, slug="reject-guards", min_reviewers=2)
    chief = register_user(email="chief.rg@uni.edu")
    editor = register_user(email="editor.rg@uni.edu")
    author = register_user(email="author.rg@uni.edu")

    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=chief["id"], role="chief_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=editor["id"], role="handling_editor")

    chief_headers = auth_headers_for(email=chief["email"])
    editor_headers = auth_headers_for(email=editor["email"])
    author_headers = auth_headers_for(email=author["email"])

    ms = _setup_under_review_manuscript(
        client,
        journal_id=journal["id"],
        author_headers=author_headers,
        chief_headers=chief_headers,
        editor_id=editor["id"],
        editor_headers=editor_headers,
    )
    ms_id = ms["id"]

    # Author cannot issue editorial decisions
    assert (
        client.post(
            f"/api/v1/manuscripts/{ms_id}/decisions",
            headers=author_headers,
            json={"decision": "accept", "decision_letter": "Self accept."},
        ).status_code
        == 403
    )

    # Reject decision does not require min_reviewers and transitions to terminal rejected state
    rejected = client.post(
        f"/api/v1/manuscripts/{ms_id}/decisions",
        headers=editor_headers,
        json={
            "decision": "reject",
            "decision_letter": "The methodology has fundamental flaws.",
        },
    )
    assert rejected.status_code == 201, rejected.text
    assert rejected.json()["decision"] == "reject"

    ms_after = client.get(f"/api/v1/manuscripts/{ms_id}", headers=author_headers).json()
    assert ms_after["status"] == "rejected"
    assert ms_after["decided_at"] is not None

    # Further decisions or resubmission on a rejected manuscript are blocked with 409 Conflict
    assert (
        client.post(
            f"/api/v1/manuscripts/{ms_id}/decisions",
            headers=chief_headers,
            json={"decision": "accept", "decision_letter": "Too late."},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/manuscripts/{ms_id}/resubmit",
            headers=author_headers,
        ).status_code
        == 409
    )

"""HTTP API tests for peer-review invitations, structured reviews, and anonymity masking."""

import io
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
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
    title: str = "Journal of Blind Peer Review",
    slug: str = "blind-peer-review",
    anonymity_mode: str = "double_anonymous",
) -> dict[str, Any]:
    resp = client.post(
        "/api/v1/journals",
        headers=admin_headers,
        json={"title": title, "slug": slug},
    )
    assert resp.status_code == 201, resp.text
    journal = resp.json()
    if anonymity_mode != "double_anonymous":
        cfg = client.patch(
            f"/api/v1/journals/{journal['id']}/workflow-config",
            headers=admin_headers,
            json={"anonymity_mode": anonymity_mode},
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
    admin_headers: dict[str, str],
    *,
    journal_id: int,
    author_headers: dict[str, str],
    chief_headers: dict[str, str],
    editor_id: int,
    editor_headers: dict[str, str],
    co_authors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    draft = client.post(
        "/api/v1/manuscripts",
        headers=author_headers,
        json={
            "journal_id": journal_id,
            "title": "Anonymized Evaluation of Distributed Consensus",
            "abstract": "We study consensus resilience under adversarial network delays.",
            "keywords": ["consensus", "distributed systems"],
            "co_authors": co_authors or [],
        },
    )
    assert draft.status_code == 201, draft.text
    ms_id = draft.json()["id"]

    upload = client.post(
        f"/api/v1/manuscripts/{ms_id}/versions",
        headers=author_headers,
        files={"file": ("consensus_v1.pdf", _blank_pdf(), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text

    submitted = client.post(f"/api/v1/manuscripts/{ms_id}/submit", headers=author_headers)
    assert submitted.status_code == 200, submitted.text

    assigned = client.post(
        f"/api/v1/manuscripts/{ms_id}/assign-editor",
        headers=chief_headers,
        json={"editor_id": editor_id},
    )
    assert assigned.status_code == 200, assigned.text

    desk = client.post(f"/api/v1/manuscripts/{ms_id}/desk-review", headers=editor_headers)
    assert desk.status_code == 200, desk.text

    under_review = client.post(
        f"/api/v1/manuscripts/{ms_id}/advance-to-review",
        headers=editor_headers,
    )
    assert under_review.status_code == 200, under_review.text
    return under_review.json()


def test_invitation_creation_rules_coi_and_duplicate_rejection(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(client, admin_headers, slug="invite-rules")
    other_journal = _create_journal(
        client,
        admin_headers,
        title="Other Journal",
        slug="other-journal",
    )

    chief = register_user(email="chief@uni.edu", full_name="Prof. Chief")
    editor = register_user(email="editor@uni.edu", full_name="Dr. Handling Editor")
    unassigned_editor = register_user(email="other.editor@uni.edu", full_name="Dr. Unassigned")
    author = register_user(email="submitter@uni.edu", full_name="Dr. Main Author")
    coauthor_by_id = register_user(email="coauthor.id@uni.edu", full_name="Dr. Coauthor ID")
    coauthor_by_email = register_user(email="coauthor.mail@uni.edu", full_name="Dr. Coauthor Mail")
    reviewer_ok = register_user(email="reviewer.ok@uni.edu", full_name="Dr. Valid Reviewer")
    reviewer_other_journal = register_user(
        email="reviewer.other@uni.edu",
        full_name="Dr. Other Journal Reviewer",
    )

    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=chief["id"], role="chief_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=editor["id"], role="handling_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=unassigned_editor["id"], role="handling_editor")
    # Even if author and co-authors hold reviewer roles, COI must block inviting them
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=author["id"], role="reviewer")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=coauthor_by_id["id"], role="reviewer")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=coauthor_by_email["id"], role="reviewer")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=reviewer_ok["id"], role="reviewer")
    _assign_role(
        client,
        admin_headers,
        journal_id=other_journal["id"],
        user_id=reviewer_other_journal["id"],
        role="reviewer",
    )

    chief_headers = auth_headers_for(email=chief["email"])
    editor_headers = auth_headers_for(email=editor["email"])
    unassigned_headers = auth_headers_for(email=unassigned_editor["email"])
    author_headers = auth_headers_for(email=author["email"])

    # Manuscript still in draft/submitted cannot receive invitations
    draft = client.post(
        "/api/v1/manuscripts",
        headers=author_headers,
        json={
            "journal_id": journal["id"],
            "title": "Not Yet Under Review",
            "abstract": "Draft abstract.",
        },
    ).json()
    too_early = client.post(
        f"/api/v1/manuscripts/{draft['id']}/invitations",
        headers=chief_headers,
        json={"reviewer_id": reviewer_ok["id"]},
    )
    assert too_early.status_code == 409
    assert too_early.json()["code"] == "manuscript_not_under_review"

    ms = _setup_under_review_manuscript(
        client,
        admin_headers,
        journal_id=journal["id"],
        author_headers=author_headers,
        chief_headers=chief_headers,
        editor_id=editor["id"],
        editor_headers=editor_headers,
        co_authors=[
            {
                "full_name": "Dr. Coauthor ID",
                "email": "different-contact@uni.edu",
                "user_id": coauthor_by_id["id"],
            },
            {
                "full_name": "Dr. Coauthor Mail",
                "email": "COAUTHOR.MAIL@UNI.EDU",
            },
        ],
    )
    ms_id = ms["id"]

    # Unassigned handling editor and author cannot invite reviewers
    assert (
        client.post(
            f"/api/v1/manuscripts/{ms_id}/invitations",
            headers=unassigned_headers,
            json={"reviewer_id": reviewer_ok["id"]},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/manuscripts/{ms_id}/invitations",
            headers=author_headers,
            json={"reviewer_id": reviewer_ok["id"]},
        ).status_code
        == 403
    )

    # User without reviewer role in this journal is rejected
    no_role = client.post(
        f"/api/v1/manuscripts/{ms_id}/invitations",
        headers=editor_headers,
        json={"reviewer_id": reviewer_other_journal["id"]},
    )
    assert no_role.status_code == 400
    assert no_role.json()["code"] == "invalid_reviewer"

    # Submitting author cannot be invited (COI)
    self_coi = client.post(
        f"/api/v1/manuscripts/{ms_id}/invitations",
        headers=editor_headers,
        json={"reviewer_id": author["id"]},
    )
    assert self_coi.status_code == 409
    assert self_coi.json()["code"] == "reviewer_conflict_of_interest"

    # Co-author matched by user_id cannot be invited (COI)
    coauthor_id_coi = client.post(
        f"/api/v1/manuscripts/{ms_id}/invitations",
        headers=editor_headers,
        json={"reviewer_id": coauthor_by_id["id"]},
    )
    assert coauthor_id_coi.status_code == 409
    assert coauthor_id_coi.json()["code"] == "reviewer_conflict_of_interest"

    # Co-author matched by email cannot be invited (COI)
    coauthor_email_coi = client.post(
        f"/api/v1/manuscripts/{ms_id}/invitations",
        headers=editor_headers,
        json={"reviewer_id": coauthor_by_email["id"]},
    )
    assert coauthor_email_coi.status_code == 409
    assert coauthor_email_coi.json()["code"] == "reviewer_conflict_of_interest"

    # Past due_at is rejected
    past_due = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    bad_due = client.post(
        f"/api/v1/manuscripts/{ms_id}/invitations",
        headers=editor_headers,
        json={"reviewer_id": reviewer_ok["id"], "due_at": past_due},
    )
    assert bad_due.status_code == 400
    assert bad_due.json()["code"] == "invalid_due_date"

    # Valid invitation by assigned Handling Editor with explicit future due_at
    future_due = (datetime.now(UTC) + timedelta(days=14)).isoformat()
    invited = client.post(
        f"/api/v1/manuscripts/{ms_id}/invitations",
        headers=editor_headers,
        json={"reviewer_id": reviewer_ok["id"], "due_at": future_due},
    )
    assert invited.status_code == 201, invited.text
    inv_data = invited.json()
    assert inv_data["manuscript_id"] == ms_id
    assert inv_data["reviewer_id"] == reviewer_ok["id"]
    assert inv_data["review_round"] == 1
    assert inv_data["status"] == "pending"

    # Duplicate active reviewer for the same round is rejected
    duplicate = client.post(
        f"/api/v1/manuscripts/{ms_id}/invitations",
        headers=chief_headers,
        json={"reviewer_id": reviewer_ok["id"]},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "duplicate_review_invitation"


def test_reviewer_invitation_listing_accept_decline_and_access_control(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(client, admin_headers, slug="invite-access")
    chief = register_user(email="chief.acc@uni.edu")
    editor = register_user(email="editor.acc@uni.edu")
    author = register_user(email="author.acc@uni.edu")
    rev_accept = register_user(email="rev.accept@uni.edu")
    rev_decline = register_user(email="rev.decline@uni.edu")
    rev_uninvited = register_user(email="rev.uninvited@uni.edu")

    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=chief["id"], role="chief_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=editor["id"], role="handling_editor")
    for rev in (rev_accept, rev_decline, rev_uninvited):
        _assign_role(client, admin_headers, journal_id=journal["id"], user_id=rev["id"], role="reviewer")

    chief_headers = auth_headers_for(email=chief["email"])
    editor_headers = auth_headers_for(email=editor["email"])
    author_headers = auth_headers_for(email=author["email"])
    accept_headers = auth_headers_for(email=rev_accept["email"])
    decline_headers = auth_headers_for(email=rev_decline["email"])
    uninvited_headers = auth_headers_for(email=rev_uninvited["email"])

    ms = _setup_under_review_manuscript(
        client,
        admin_headers,
        journal_id=journal["id"],
        author_headers=author_headers,
        chief_headers=chief_headers,
        editor_id=editor["id"],
        editor_headers=editor_headers,
    )
    ms_id = ms["id"]

    inv1 = client.post(
        f"/api/v1/manuscripts/{ms_id}/invitations",
        headers=editor_headers,
        json={"reviewer_id": rev_accept["id"]},
    ).json()
    inv2 = client.post(
        f"/api/v1/manuscripts/{ms_id}/invitations",
        headers=editor_headers,
        json={"reviewer_id": rev_decline["id"]},
    ).json()

    # Reviewer lists own invitations
    my_invs = client.get("/api/v1/review-invitations", headers=accept_headers)
    assert my_invs.status_code == 200
    assert my_invs.json()["total"] == 1
    assert my_invs.json()["items"][0]["id"] == inv1["id"]

    # Another user cannot accept or decline someone else's invitation
    assert (
        client.post(f"/api/v1/review-invitations/{inv1['id']}/accept", headers=decline_headers).status_code
        == 403
    )
    assert (
        client.post(f"/api/v1/review-invitations/{inv1['id']}/decline", headers=editor_headers).status_code
        == 403
    )

    # Pending, declined, and uninvited reviewers cannot access manuscript or download PDF
    for hdrs in (accept_headers, decline_headers, uninvited_headers):
        assert client.get(f"/api/v1/manuscripts/{ms_id}", headers=hdrs).status_code == 403
        assert (
            client.get(f"/api/v1/manuscripts/{ms_id}/versions/1/download", headers=hdrs).status_code
            == 403
        )

    # Decline invitation with reason
    declined = client.post(
        f"/api/v1/review-invitations/{inv2['id']}/decline",
        headers=decline_headers,
        json={"decline_reason": "Schedule conflict this month."},
    )
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "declined"
    assert declined.json()["decline_reason"] == "Schedule conflict this month."
    assert declined.json()["responded_at"] is not None

    # Declined reviewer still receives 403 on manuscript & PDF, and cannot accept after declining
    assert client.get(f"/api/v1/manuscripts/{ms_id}", headers=decline_headers).status_code == 403
    assert (
        client.get(f"/api/v1/manuscripts/{ms_id}/versions/1/download", headers=decline_headers).status_code
        == 403
    )
    assert (
        client.post(f"/api/v1/review-invitations/{inv2['id']}/accept", headers=decline_headers).status_code
        == 409
    )

    # Accept invitation
    accepted = client.post(
        f"/api/v1/review-invitations/{inv1['id']}/accept",
        headers=accept_headers,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["responded_at"] is not None

    # Accepted reviewer can view manuscript and download current version PDF
    ms_view = client.get(f"/api/v1/manuscripts/{ms_id}", headers=accept_headers)
    assert ms_view.status_code == 200, ms_view.text
    assert ms_view.json()["title"] == ms["title"]

    pdf_dl = client.get(
        f"/api/v1/manuscripts/{ms_id}/versions/1/download",
        headers=accept_headers,
    )
    assert pdf_dl.status_code == 200
    assert pdf_dl.content.startswith(b"%PDF-")


def test_structured_review_submission_validation_and_duplicate_rejection(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(client, admin_headers, slug="review-submit")
    chief = register_user(email="chief.sub@uni.edu")
    editor = register_user(email="editor.sub@uni.edu")
    author = register_user(email="author.sub@uni.edu")
    reviewer = register_user(email="reviewer.sub@uni.edu")
    other_user = register_user(email="other.sub@uni.edu")

    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=chief["id"], role="chief_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=editor["id"], role="handling_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=reviewer["id"], role="reviewer")

    chief_headers = auth_headers_for(email=chief["email"])
    editor_headers = auth_headers_for(email=editor["email"])
    author_headers = auth_headers_for(email=author["email"])
    reviewer_headers = auth_headers_for(email=reviewer["email"])
    other_headers = auth_headers_for(email=other_user["email"])

    ms = _setup_under_review_manuscript(
        client,
        admin_headers,
        journal_id=journal["id"],
        author_headers=author_headers,
        chief_headers=chief_headers,
        editor_id=editor["id"],
        editor_headers=editor_headers,
    )

    inv = client.post(
        f"/api/v1/manuscripts/{ms['id']}/invitations",
        headers=editor_headers,
        json={"reviewer_id": reviewer["id"]},
    ).json()

    valid_payload = {
        "originality_score": 5,
        "methodology_score": 4,
        "clarity_score": 4,
        "significance_score": 5,
        "recommendation": "minor_revision",
        "comments_to_author": "Strong contribution; clarify theorem 2 assumptions.",
        "confidential_comments_to_editor": "Recommend minor revision and quick re-check.",
    }

    # Cannot submit before accepting
    before_accept = client.post(
        f"/api/v1/review-invitations/{inv['id']}/review",
        headers=reviewer_headers,
        json=valid_payload,
    )
    assert before_accept.status_code == 409
    assert before_accept.json()["code"] == "invitation_not_accepted"

    # Accept invitation
    assert (
        client.post(f"/api/v1/review-invitations/{inv['id']}/accept", headers=reviewer_headers).status_code
        == 200
    )

    # Other user cannot submit review for this invitation
    assert (
        client.post(
            f"/api/v1/review-invitations/{inv['id']}/review",
            headers=other_headers,
            json=valid_payload,
        ).status_code
        == 403
    )

    # Out-of-range score rejected with 422
    bad_score = client.post(
        f"/api/v1/review-invitations/{inv['id']}/review",
        headers=reviewer_headers,
        json={**valid_payload, "originality_score": 6},
    )
    assert bad_score.status_code == 422

    # Submit valid review
    created = client.post(
        f"/api/v1/review-invitations/{inv['id']}/review",
        headers=reviewer_headers,
        json=valid_payload,
    )
    assert created.status_code == 201, created.text
    review_data = created.json()
    assert review_data["originality_score"] == 5
    assert review_data["recommendation"] == "minor_revision"
    assert review_data["reviewer_label"] == "Reviewer #1"

    # Invitation is now completed
    inv_after = client.get(f"/api/v1/review-invitations/{inv['id']}", headers=reviewer_headers)
    assert inv_after.status_code == 200
    assert inv_after.json()["status"] == "completed"

    # Duplicate submission for the same invitation is rejected
    dup = client.post(
        f"/api/v1/review-invitations/{inv['id']}/review",
        headers=reviewer_headers,
        json=valid_payload,
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "review_already_submitted"


def test_double_anonymous_mode_zero_leakage(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(
        client,
        admin_headers,
        slug="double-anon-security",
        anonymity_mode="double_anonymous",
    )
    chief = register_user(email="chief.da@uni.edu", full_name="Prof. Chief DA")
    editor = register_user(email="editor.da@uni.edu", full_name="Dr. Editor DA")
    author = register_user(
        email="secret.author.name@stanford-example.edu",
        full_name="Dr. Secret Submitter",
        affiliation="Secret Stanford Lab",
    )
    rev1 = register_user(
        email="secret.reviewer.one@mit-example.edu",
        full_name="Prof. Hidden Reviewer One",
        affiliation="Hidden MIT Group",
    )
    rev2 = register_user(
        email="secret.reviewer.two@ox-example.edu",
        full_name="Dr. Hidden Reviewer Two",
        affiliation="Hidden Oxford Institute",
    )

    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=chief["id"], role="chief_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=editor["id"], role="handling_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=rev1["id"], role="reviewer")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=rev2["id"], role="reviewer")

    chief_headers = auth_headers_for(email=chief["email"])
    editor_headers = auth_headers_for(email=editor["email"])
    author_headers = auth_headers_for(email=author["email"])
    rev1_headers = auth_headers_for(email=rev1["email"])
    rev2_headers = auth_headers_for(email=rev2["email"])

    ms = _setup_under_review_manuscript(
        client,
        admin_headers,
        journal_id=journal["id"],
        author_headers=author_headers,
        chief_headers=chief_headers,
        editor_id=editor["id"],
        editor_headers=editor_headers,
        co_authors=[
            {
                "full_name": "Dr. Secret Submitter",
                "email": "secret.author.name@stanford-example.edu",
                "affiliation": "Secret Stanford Lab",
                "orcid": "0000-0002-1825-0097",
                "is_corresponding": True,
                "user_id": author["id"],
            },
            {
                "full_name": "Dr. Secret CoAuthor",
                "email": "secret.coauthor@berkeley-example.edu",
                "affiliation": "Secret Berkeley Department",
                "orcid": "0000-0001-5109-3700",
            },
        ],
    )
    ms_id = ms["id"]

    inv1 = client.post(
        f"/api/v1/manuscripts/{ms_id}/invitations",
        headers=editor_headers,
        json={"reviewer_id": rev1["id"]},
    ).json()
    inv2 = client.post(
        f"/api/v1/manuscripts/{ms_id}/invitations",
        headers=editor_headers,
        json={"reviewer_id": rev2["id"]},
    ).json()

    assert client.post(f"/api/v1/review-invitations/{inv1['id']}/accept", headers=rev1_headers).status_code == 200
    assert client.post(f"/api/v1/review-invitations/{inv2['id']}/accept", headers=rev2_headers).status_code == 200

    # 1. Accepted reviewer fetches manuscript details -> zero author leakage
    ms_for_rev = client.get(f"/api/v1/manuscripts/{ms_id}", headers=rev1_headers)
    assert ms_for_rev.status_code == 200, ms_for_rev.text
    ms_body = ms_for_rev.json()
    assert ms_body["submitter_id"] is None
    assert ms_body["co_authors"] == []
    raw_ms = ms_for_rev.text
    for forbidden_str in (
        "Dr. Secret Submitter",
        "secret.author.name@stanford-example.edu",
        "Secret Stanford Lab",
        "0000-0002-1825-0097",
        "Dr. Secret CoAuthor",
        "secret.coauthor@berkeley-example.edu",
        "Secret Berkeley Department",
        "0000-0001-5109-3700",
    ):
        assert forbidden_str not in raw_ms

    # Versions and status history also strip submitter/uploader IDs for reviewer
    versions_for_rev = client.get(f"/api/v1/manuscripts/{ms_id}/versions", headers=rev1_headers)
    assert versions_for_rev.status_code == 200
    assert all(v["uploaded_by_id"] is None for v in versions_for_rev.json())

    history_for_rev = client.get(f"/api/v1/manuscripts/{ms_id}/status-history", headers=rev1_headers)
    assert history_for_rev.status_code == 200
    assert all(h["changed_by_id"] is None for h in history_for_rev.json())

    # 2. Both reviewers submit reviews with confidential editor comments
    secret_note_1 = "CONFIDENTIAL_NOTE_ONE_DO_NOT_LEAK_TO_AUTHOR"
    secret_note_2 = "CONFIDENTIAL_NOTE_TWO_EYES_ONLY_EDITOR"

    assert (
        client.post(
            f"/api/v1/review-invitations/{inv1['id']}/review",
            headers=rev1_headers,
            json={
                "originality_score": 5,
                "methodology_score": 4,
                "clarity_score": 5,
                "significance_score": 4,
                "recommendation": "accept",
                "comments_to_author": "Excellent paper.",
                "confidential_comments_to_editor": secret_note_1,
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/v1/review-invitations/{inv2['id']}/review",
            headers=rev2_headers,
            json={
                "originality_score": 4,
                "methodology_score": 3,
                "clarity_score": 4,
                "significance_score": 4,
                "recommendation": "minor_revision",
                "comments_to_author": "Please expand the evaluation section.",
                "confidential_comments_to_editor": secret_note_2,
            },
        ).status_code
        == 201
    )

    # 3. Before an editorial decision is issued, author sees no reviews for the undecided round
    before_decision = client.get(f"/api/v1/manuscripts/{ms_id}/reviews", headers=author_headers)
    assert before_decision.status_code == 200
    assert before_decision.json() == []

    # Editor issues a decision for round 1
    dec = client.post(
        f"/api/v1/manuscripts/{ms_id}/decisions",
        headers=editor_headers,
        json={
            "decision": "minor_revision",
            "decision_letter": "Please address reviewer suggestions.",
        },
    )
    assert dec.status_code == 201, dec.text

    # Author now fetches reviews -> anonymous labels only, zero reviewer identity or confidential note leakage
    reviews_for_author = client.get(f"/api/v1/manuscripts/{ms_id}/reviews", headers=author_headers)
    assert reviews_for_author.status_code == 200, reviews_for_author.text
    author_reviews = reviews_for_author.json()
    assert len(author_reviews) == 2
    assert [r["reviewer_label"] for r in author_reviews] == ["Reviewer #1", "Reviewer #2"]

    for item in author_reviews:
        assert item["reviewer_id"] is None
        assert item["reviewer_name"] is None
        assert item["reviewer_email"] is None
        assert item["reviewer_affiliation"] is None
        assert item["confidential_comments_to_editor"] is None

    raw_reviews = reviews_for_author.text
    for forbidden_str in (
        "Prof. Hidden Reviewer One",
        "secret.reviewer.one@mit-example.edu",
        "Hidden MIT Group",
        "Dr. Hidden Reviewer Two",
        "secret.reviewer.two@ox-example.edu",
        "Hidden Oxford Institute",
        secret_note_1,
        secret_note_2,
    ):
        assert forbidden_str not in raw_reviews

    # 4. Reviewer 1 only sees their own review (never Reviewer 2's identity or confidential note)
    rev1_list = client.get(f"/api/v1/manuscripts/{ms_id}/reviews", headers=rev1_headers)
    assert rev1_list.status_code == 200
    assert len(rev1_list.json()) == 1
    assert rev1_list.json()[0]["reviewer_id"] == rev1["id"]
    assert secret_note_2 not in rev1_list.text
    assert "Prof. Hidden Reviewer Two" not in rev1_list.text


def test_single_anonymous_and_open_modes_masking_rules(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    single_journal = _create_journal(
        client,
        admin_headers,
        title="Single Anonymous Journal",
        slug="single-anon-journal",
        anonymity_mode="single_anonymous",
    )
    open_journal = _create_journal(
        client,
        admin_headers,
        title="Open Review Journal",
        slug="open-review-journal",
        anonymity_mode="open",
    )

    chief = register_user(email="chief.modes@uni.edu")
    editor = register_user(email="editor.modes@uni.edu")
    author = register_user(
        email="visible.author@uni.edu",
        full_name="Dr. Visible Author",
        affiliation="Visible University",
    )
    reviewer = register_user(
        email="mode.reviewer@uni.edu",
        full_name="Prof. Mode Reviewer",
        affiliation="Reviewer Institute",
    )

    for j in (single_journal, open_journal):
        _assign_role(client, admin_headers, journal_id=j["id"], user_id=chief["id"], role="chief_editor")
        _assign_role(client, admin_headers, journal_id=j["id"], user_id=editor["id"], role="handling_editor")
        _assign_role(client, admin_headers, journal_id=j["id"], user_id=reviewer["id"], role="reviewer")

    chief_headers = auth_headers_for(email=chief["email"])
    editor_headers = auth_headers_for(email=editor["email"])
    author_headers = auth_headers_for(email=author["email"])
    reviewer_headers = auth_headers_for(email=reviewer["email"])

    co_authors = [
        {
            "full_name": "Dr. Visible Author",
            "email": "visible.author@uni.edu",
            "affiliation": "Visible University",
            "orcid": "0000-0002-1825-0097",
            "is_corresponding": True,
            "user_id": author["id"],
        }
    ]

    # --- SINGLE ANONYMOUS ---
    ms_single = _setup_under_review_manuscript(
        client,
        admin_headers,
        journal_id=single_journal["id"],
        author_headers=author_headers,
        chief_headers=chief_headers,
        editor_id=editor["id"],
        editor_headers=editor_headers,
        co_authors=co_authors,
    )
    inv_single = client.post(
        f"/api/v1/manuscripts/{ms_single['id']}/invitations",
        headers=editor_headers,
        json={"reviewer_id": reviewer["id"]},
    ).json()
    assert client.post(f"/api/v1/review-invitations/{inv_single['id']}/accept", headers=reviewer_headers).status_code == 200

    # Reviewer sees author details in single_anonymous
    ms_single_rev = client.get(f"/api/v1/manuscripts/{ms_single['id']}", headers=reviewer_headers)
    assert ms_single_rev.status_code == 200
    assert ms_single_rev.json()["submitter_id"] == author["id"]
    assert len(ms_single_rev.json()["co_authors"]) == 1
    assert ms_single_rev.json()["co_authors"][0]["full_name"] == "Dr. Visible Author"

    secret_single = "SINGLE_ANON_CONFIDENTIAL_EDITOR_ONLY"
    assert (
        client.post(
            f"/api/v1/review-invitations/{inv_single['id']}/review",
            headers=reviewer_headers,
            json={
                "originality_score": 4,
                "methodology_score": 4,
                "clarity_score": 4,
                "significance_score": 4,
                "recommendation": "accept",
                "comments_to_author": "Solid single-anonymous review.",
                "confidential_comments_to_editor": secret_single,
            },
        ).status_code
        == 201
    )

    # Before decision, author cannot see reviews yet
    assert (
        client.get(f"/api/v1/manuscripts/{ms_single['id']}/reviews", headers=author_headers).json()
        == []
    )

    # Issue decision so author can read round-1 feedback
    assert (
        client.post(
            f"/api/v1/manuscripts/{ms_single['id']}/decisions",
            headers=editor_headers,
            json={"decision": "minor_revision", "decision_letter": "Minor edits requested."},
        ).status_code
        == 201
    )

    # Author still cannot see reviewer identity or confidential comments
    single_reviews_author = client.get(
        f"/api/v1/manuscripts/{ms_single['id']}/reviews",
        headers=author_headers,
    )
    assert single_reviews_author.status_code == 200
    sr = single_reviews_author.json()[0]
    assert sr["reviewer_label"] == "Reviewer #1"
    assert sr["reviewer_id"] is None
    assert sr["reviewer_name"] is None
    assert sr["reviewer_email"] is None
    assert sr["reviewer_affiliation"] is None
    assert sr["confidential_comments_to_editor"] is None
    assert "Prof. Mode Reviewer" not in single_reviews_author.text
    assert "mode.reviewer@uni.edu" not in single_reviews_author.text
    assert secret_single not in single_reviews_author.text

    # --- OPEN REVIEW ---
    ms_open = _setup_under_review_manuscript(
        client,
        admin_headers,
        journal_id=open_journal["id"],
        author_headers=author_headers,
        chief_headers=chief_headers,
        editor_id=editor["id"],
        editor_headers=editor_headers,
        co_authors=co_authors,
    )
    inv_open = client.post(
        f"/api/v1/manuscripts/{ms_open['id']}/invitations",
        headers=editor_headers,
        json={"reviewer_id": reviewer["id"]},
    ).json()
    assert client.post(f"/api/v1/review-invitations/{inv_open['id']}/accept", headers=reviewer_headers).status_code == 200

    # Reviewer sees author details in open mode
    ms_open_rev = client.get(f"/api/v1/manuscripts/{ms_open['id']}", headers=reviewer_headers)
    assert ms_open_rev.status_code == 200
    assert ms_open_rev.json()["submitter_id"] == author["id"]
    assert ms_open_rev.json()["co_authors"][0]["full_name"] == "Dr. Visible Author"

    secret_open = "OPEN_MODE_STILL_CONFIDENTIAL_TO_EDITOR"
    assert (
        client.post(
            f"/api/v1/review-invitations/{inv_open['id']}/review",
            headers=reviewer_headers,
            json={
                "originality_score": 5,
                "methodology_score": 5,
                "clarity_score": 5,
                "significance_score": 5,
                "recommendation": "accept",
                "comments_to_author": "Transparent open review.",
                "confidential_comments_to_editor": secret_open,
            },
        ).status_code
        == 201
    )

    # Issue decision so author can read open-mode round-1 feedback
    assert (
        client.post(
            f"/api/v1/manuscripts/{ms_open['id']}/decisions",
            headers=editor_headers,
            json={"decision": "minor_revision", "decision_letter": "Minor edits requested."},
        ).status_code
        == 201
    )

    # Author sees reviewer identity in open mode, but NEVER confidential_comments_to_editor
    open_reviews_author = client.get(
        f"/api/v1/manuscripts/{ms_open['id']}/reviews",
        headers=author_headers,
    )
    assert open_reviews_author.status_code == 200
    orr = open_reviews_author.json()[0]
    assert orr["reviewer_id"] == reviewer["id"]
    assert orr["reviewer_name"] == "Prof. Mode Reviewer"
    assert orr["reviewer_email"] == "mode.reviewer@uni.edu"
    assert orr["reviewer_affiliation"] == "Reviewer Institute"
    assert orr["confidential_comments_to_editor"] is None
    assert secret_open not in open_reviews_author.text


def test_editors_and_admin_view_all_invitations_and_unmasked_reviews(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(
        client,
        admin_headers,
        slug="editorial-visibility",
        anonymity_mode="double_anonymous",
    )
    other_journal = _create_journal(
        client,
        admin_headers,
        title="Separate Journal",
        slug="separate-journal",
    )

    chief = register_user(email="chief.vis@uni.edu")
    other_chief = register_user(email="chief.other@uni.edu")
    editor = register_user(email="editor.vis@uni.edu")
    author = register_user(email="author.vis@uni.edu")
    reviewer = register_user(
        email="reviewer.vis@uni.edu",
        full_name="Dr. Full Identity Reviewer",
        affiliation="Visibility University",
    )

    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=chief["id"], role="chief_editor")
    _assign_role(client, admin_headers, journal_id=other_journal["id"], user_id=other_chief["id"], role="chief_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=editor["id"], role="handling_editor")
    _assign_role(client, admin_headers, journal_id=journal["id"], user_id=reviewer["id"], role="reviewer")

    chief_headers = auth_headers_for(email=chief["email"])
    other_chief_headers = auth_headers_for(email=other_chief["email"])
    editor_headers = auth_headers_for(email=editor["email"])
    author_headers = auth_headers_for(email=author["email"])
    reviewer_headers = auth_headers_for(email=reviewer["email"])

    ms = _setup_under_review_manuscript(
        client,
        admin_headers,
        journal_id=journal["id"],
        author_headers=author_headers,
        chief_headers=chief_headers,
        editor_id=editor["id"],
        editor_headers=editor_headers,
    )
    ms_id = ms["id"]

    inv = client.post(
        f"/api/v1/manuscripts/{ms_id}/invitations",
        headers=editor_headers,
        json={"reviewer_id": reviewer["id"]},
    ).json()
    assert client.post(f"/api/v1/review-invitations/{inv['id']}/accept", headers=reviewer_headers).status_code == 200

    secret_editor_note = "CONFIDENTIAL_FOR_EDITORIAL_BOARD_ONLY"
    assert (
        client.post(
            f"/api/v1/review-invitations/{inv['id']}/review",
            headers=reviewer_headers,
            json={
                "originality_score": 4,
                "methodology_score": 5,
                "clarity_score": 4,
                "significance_score": 5,
                "recommendation": "accept",
                "comments_to_author": "Well executed study.",
                "confidential_comments_to_editor": secret_editor_note,
            },
        ).status_code
        == 201
    )

    # Assigned Handling Editor, Chief Editor of same journal, and System Admin all see unmasked data
    for hdrs in (editor_headers, chief_headers, admin_headers):
        invs_resp = client.get(f"/api/v1/manuscripts/{ms_id}/invitations", headers=hdrs)
        assert invs_resp.status_code == 200, invs_resp.text
        assert len(invs_resp.json()) == 1
        assert invs_resp.json()[0]["reviewer_id"] == reviewer["id"]
        assert invs_resp.json()[0]["status"] == "completed"

        revs_resp = client.get(f"/api/v1/manuscripts/{ms_id}/reviews", headers=hdrs)
        assert revs_resp.status_code == 200, revs_resp.text
        rev_item = revs_resp.json()[0]
        assert rev_item["reviewer_id"] == reviewer["id"]
        assert rev_item["reviewer_name"] == "Dr. Full Identity Reviewer"
        assert rev_item["reviewer_email"] == "reviewer.vis@uni.edu"
        assert rev_item["reviewer_affiliation"] == "Visibility University"
        assert rev_item["confidential_comments_to_editor"] == secret_editor_note

    # Author, reviewer, and Chief Editor of another journal cannot view manuscript invitations
    for hdrs in (author_headers, reviewer_headers, other_chief_headers):
        assert (
            client.get(f"/api/v1/manuscripts/{ms_id}/invitations", headers=hdrs).status_code
            == 403
        )

    # Chief Editor of another journal cannot view reviews either
    assert (
        client.get(f"/api/v1/manuscripts/{ms_id}/reviews", headers=other_chief_headers).status_code
        == 403
    )

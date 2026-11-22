"""HTTP API tests for manuscript drafts, co-authors, versioned PDF storage, and access control."""

import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.manuscript import Manuscript, ManuscriptStatus, ManuscriptVersion


def _build_pdf_with_text(text: str) -> bytes:
    """Generate a valid minimal single-page PDF containing extractable ASCII text."""
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET\n".encode("latin-1")

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n"
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\n"
            b"endobj\n"
        ),
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        (
            f"5 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
            + stream
            + b"endstream\nendobj\n"
        ),
    ]

    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets: list[int] = [0]
    for obj in objects:
        offsets.append(buffer.tell())
        buffer.write(obj)

    xref_pos = buffer.tell()
    buffer.write(f"xref\n0 {len(offsets)}\n".encode("latin-1"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode("latin-1"))

    buffer.write(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("latin-1")
    )
    return buffer.getvalue()


def _build_blank_pdf() -> bytes:
    """Generate a valid PDF containing a single blank page (no extractable text)."""
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _create_journal(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    title: str = "Journal of Software Systems",
    slug: str = "software-systems",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/journals",
        headers=admin_headers,
        json={
            "title": title,
            "slug": slug,
            "description": "Peer-reviewed software engineering research.",
            "scope_keywords": ["software engineering", "distributed systems"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_manuscript_draft_with_ordered_co_authors(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(client, admin_headers)
    author = register_user(email="lead.author@uni.edu", full_name="Dr. Lead Author")
    headers = auth_headers_for(email=author["email"])

    resp = client.post(
        "/api/v1/manuscripts",
        headers=headers,
        json={
            "journal_id": journal["id"],
            "title": "Formal Verification of Peer-Review Workflows",
            "abstract": "We present a state-machine model for scholarly publishing.",
            "keywords": ["Formal Methods", "Peer Review", "formal methods"],
            "subject_area": "Software Engineering",
            "co_authors": [
                {
                    "full_name": "Dr. Lead Author",
                    "email": "LEAD.AUTHOR@uni.edu",
                    "affiliation": "University A",
                    "orcid": "0000-0002-1825-0097",
                    "is_corresponding": True,
                    "user_id": author["id"],
                },
                {
                    "full_name": "Prof. Second Author",
                    "email": "second@uni.edu",
                    "affiliation": "University B",
                    "is_corresponding": False,
                },
                {
                    "full_name": "Dr. Third Author",
                    "email": "third@uni.edu",
                    "is_corresponding": False,
                },
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["journal_id"] == journal["id"]
    assert body["submitter_id"] == author["id"]
    assert body["status"] == "draft"
    assert body["current_version_number"] == 0
    assert body["current_review_round"] == 0
    assert body["keywords"] == ["Formal Methods", "Peer Review"]
    assert body["subject_area"] == "Software Engineering"

    co_authors = body["co_authors"]
    assert [a["author_order"] for a in co_authors] == [1, 2, 3]
    assert [a["full_name"] for a in co_authors] == [
        "Dr. Lead Author",
        "Prof. Second Author",
        "Dr. Third Author",
    ]
    assert co_authors[0]["email"] == "lead.author@uni.edu"
    assert co_authors[0]["orcid"] == "0000-0002-1825-0097"
    assert co_authors[0]["is_corresponding"] is True
    assert co_authors[1]["is_corresponding"] is False


def test_create_draft_rejects_unauthenticated_or_inactive_journal(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(client, admin_headers, slug="inactive-journal")
    deactivate = client.patch(
        f"/api/v1/journals/{journal['id']}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert deactivate.status_code == 200

    unauth = client.post(
        "/api/v1/manuscripts",
        json={
            "journal_id": journal["id"],
            "title": "Unauthenticated Draft",
            "abstract": "Should fail.",
        },
    )
    assert unauth.status_code == 401

    author = register_user(email="author2@uni.edu")
    headers = auth_headers_for(email=author["email"])
    inactive_resp = client.post(
        "/api/v1/manuscripts",
        headers=headers,
        json={
            "journal_id": journal["id"],
            "title": "Draft in Inactive Journal",
            "abstract": "Should fail with 400.",
        },
    )
    assert inactive_resp.status_code == 400
    assert inactive_resp.json()["code"] == "journal_inactive"


def test_update_draft_metadata_and_co_author_reordering_and_permissions(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
    db_session: Session,
) -> None:
    journal = _create_journal(client, admin_headers)
    owner = register_user(email="owner@uni.edu")
    other = register_user(email="other@uni.edu")
    owner_headers = auth_headers_for(email=owner["email"])
    other_headers = auth_headers_for(email=other["email"])

    created = client.post(
        "/api/v1/manuscripts",
        headers=owner_headers,
        json={
            "journal_id": journal["id"],
            "title": "Initial Title",
            "abstract": "Initial abstract.",
            "co_authors": [
                {"full_name": "Alice First", "email": "alice@uni.edu", "is_corresponding": True},
                {"full_name": "Bob Second", "email": "bob@uni.edu", "is_corresponding": False},
            ],
        },
    ).json()
    manuscript_id = created["id"]

    # Another author cannot edit this draft
    forbidden = client.patch(
        f"/api/v1/manuscripts/{manuscript_id}",
        headers=other_headers,
        json={"title": "Hijacked Title"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "manuscript_edit_forbidden"

    # Submitting author updates metadata and reverses co-author order
    updated = client.patch(
        f"/api/v1/manuscripts/{manuscript_id}",
        headers=owner_headers,
        json={
            "title": "Revised Draft Title",
            "keywords": ["AI", "Indexing"],
            "co_authors": [
                {"full_name": "Bob First Now", "email": "bob@uni.edu", "is_corresponding": True},
                {"full_name": "Alice Second Now", "email": "alice@uni.edu", "is_corresponding": False},
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["title"] == "Revised Draft Title"
    assert body["keywords"] == ["AI", "Indexing"]
    assert [(a["author_order"], a["full_name"]) for a in body["co_authors"]] == [
        (1, "Bob First Now"),
        (2, "Alice Second Now"),
    ]

    # Once manuscript leaves draft status, editing is blocked with 409 Conflict
    manuscript_row = db_session.get(Manuscript, manuscript_id)
    assert manuscript_row is not None
    manuscript_row.status = ManuscriptStatus.SUBMITTED.value
    db_session.commit()

    locked = client.patch(
        f"/api/v1/manuscripts/{manuscript_id}",
        headers=owner_headers,
        json={"title": "Post-submission Edit"},
    )
    assert locked.status_code == 409
    assert locked.json()["code"] == "manuscript_not_editable"


def test_pdf_upload_text_extraction_versioning_and_graceful_unextractable_pdf(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
    storage_dir: Path,
    db_session: Session,
) -> None:
    journal = _create_journal(client, admin_headers)
    author = register_user(email="pdf.author@uni.edu")
    headers = auth_headers_for(email=author["email"])

    draft = client.post(
        "/api/v1/manuscripts",
        headers=headers,
        json={
            "journal_id": journal["id"],
            "title": "Graph Neural Indexing",
            "abstract": "Abstract for PDF upload test.",
        },
    ).json()
    manuscript_id = draft["id"]

    pdf_v1 = _build_pdf_with_text("Quantum Graph Neural Networks for Scholarly Indexing")
    upload_v1 = client.post(
        f"/api/v1/manuscripts/{manuscript_id}/versions",
        headers=headers,
        files={"file": ("../../evil/path/paper_v1.pdf", pdf_v1, "application/pdf")},
    )
    assert upload_v1.status_code == 201, upload_v1.text
    v1_body = upload_v1.json()
    assert v1_body["version_number"] == 1
    assert v1_body["original_filename"] == "paper_v1.pdf"
    assert v1_body["content_type"] == "application/pdf"
    assert v1_body["file_size_bytes"] == len(pdf_v1)
    assert v1_body["extracted_text_length"] > 0

    # Verify extracted text and isolated storage file on disk
    v1_row = db_session.get(ManuscriptVersion, v1_body["id"])
    assert v1_row is not None
    assert "Quantum Graph Neural Networks" in v1_row.extracted_text
    stored_file = storage_dir / v1_row.file_key
    assert stored_file.is_file()
    assert stored_file.read_bytes() == pdf_v1

    # Upload v2: blank PDF (valid PDF, zero extractable text) -> succeeds gracefully
    pdf_v2 = _build_blank_pdf()
    upload_v2 = client.post(
        f"/api/v1/manuscripts/{manuscript_id}/versions",
        headers=headers,
        files={"file": ("blank_scan.pdf", pdf_v2, "application/pdf")},
        data={"response_to_reviewers": "Addressed formatting comments."},
    )
    assert upload_v2.status_code == 201, upload_v2.text
    v2_body = upload_v2.json()
    assert v2_body["version_number"] == 2
    assert v2_body["extracted_text_length"] == 0
    assert v2_body["response_to_reviewers"] == "Addressed formatting comments."

    # Upload v3: malformed PDF body starting with %PDF- -> pypdf fails internally but upload does not crash
    corrupt_pdf = b"%PDF-1.4\nnot-actually-valid-xref-content"
    upload_v3 = client.post(
        f"/api/v1/manuscripts/{manuscript_id}/versions",
        headers=headers,
        files={"file": ("corrupt_body.pdf", corrupt_pdf, "application/pdf")},
    )
    assert upload_v3.status_code == 201, upload_v3.text
    assert upload_v3.json()["version_number"] == 3
    assert upload_v3.json()["extracted_text_length"] == 0

    # Inspect manuscript details and version history
    detail = client.get(f"/api/v1/manuscripts/{manuscript_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["current_version_number"] == 3

    history = client.get(f"/api/v1/manuscripts/{manuscript_id}/versions", headers=headers)
    assert history.status_code == 200
    assert [v["version_number"] for v in history.json()] == [1, 2, 3]


def test_pdf_upload_rejects_invalid_mime_signature_empty_and_oversized(
    client: TestClient,
    test_settings: Settings,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(client, admin_headers)
    author = register_user(email="validator.author@uni.edu")
    headers = auth_headers_for(email=author["email"])

    draft = client.post(
        "/api/v1/manuscripts",
        headers=headers,
        json={
            "journal_id": journal["id"],
            "title": "Upload Validation Test",
            "abstract": "Testing file rejections.",
        },
    ).json()
    manuscript_id = draft["id"]

    # Non-PDF MIME type -> 415
    wrong_mime = client.post(
        f"/api/v1/manuscripts/{manuscript_id}/versions",
        headers=headers,
        files={"file": ("notes.txt", b"hello world", "text/plain")},
    )
    assert wrong_mime.status_code == 415
    assert wrong_mime.json()["code"] == "invalid_file_type"

    # Spoofed PDF MIME type without %PDF- signature -> 400
    bad_sig = client.post(
        f"/api/v1/manuscripts/{manuscript_id}/versions",
        headers=headers,
        files={"file": ("fake.pdf", b"NOT_A_PDF_HEADER", "application/pdf")},
    )
    assert bad_sig.status_code == 400
    assert bad_sig.json()["code"] == "invalid_pdf_signature"

    # Empty file -> 400
    empty_resp = client.post(
        f"/api/v1/manuscripts/{manuscript_id}/versions",
        headers=headers,
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert empty_resp.status_code == 400
    assert empty_resp.json()["code"] == "empty_file"

    # Oversized file -> 413 (override max_upload_size_bytes to 100 bytes for fast test)
    small_limit_settings = test_settings.model_copy(update={"max_upload_size_bytes": 100})
    client.app.dependency_overrides[get_settings] = lambda: small_limit_settings
    oversized_pdf = b"%PDF-1.4\n" + (b"A" * 200)
    oversized_resp = client.post(
        f"/api/v1/manuscripts/{manuscript_id}/versions",
        headers=headers,
        files={"file": ("huge.pdf", oversized_pdf, "application/pdf")},
    )
    assert oversized_resp.status_code == 413
    assert oversized_resp.json()["code"] == "file_too_large"


def test_list_own_submissions_pagination_and_isolation(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
) -> None:
    journal = _create_journal(client, admin_headers)
    author_a = register_user(email="author.a@uni.edu")
    author_b = register_user(email="author.b@uni.edu")
    headers_a = auth_headers_for(email=author_a["email"])
    headers_b = auth_headers_for(email=author_b["email"])

    for idx in range(3):
        resp = client.post(
            "/api/v1/manuscripts",
            headers=headers_a,
            json={
                "journal_id": journal["id"],
                "title": f"Author A Paper {idx + 1}",
                "abstract": "Abstract text.",
            },
        )
        assert resp.status_code == 201

    resp_b = client.post(
        "/api/v1/manuscripts",
        headers=headers_b,
        json={
            "journal_id": journal["id"],
            "title": "Author B Secret Paper",
            "abstract": "Abstract text.",
        },
    )
    assert resp_b.status_code == 201

    page_1 = client.get("/api/v1/manuscripts?page=1&page_size=2", headers=headers_a)
    assert page_1.status_code == 200
    data_1 = page_1.json()
    assert data_1["total"] == 3
    assert data_1["page"] == 1
    assert data_1["page_size"] == 2
    assert len(data_1["items"]) == 2
    assert all(item["submitter_id"] == author_a["id"] for item in data_1["items"])

    page_2 = client.get("/api/v1/manuscripts?page=2&page_size=2", headers=headers_a)
    assert page_2.status_code == 200
    assert len(page_2.json()["items"]) == 1


def test_download_and_inspect_access_control_matrix(
    client: TestClient,
    admin_headers: dict[str, str],
    register_user: Callable[..., dict[str, Any]],
    auth_headers_for: Callable[..., dict[str, str]],
    db_session: Session,
) -> None:
    journal_1 = _create_journal(client, admin_headers, title="Journal One", slug="journal-one")
    journal_2 = _create_journal(client, admin_headers, title="Journal Two", slug="journal-two")

    author = register_user(email="submitting.author@uni.edu")
    other_author = register_user(email="other.author@uni.edu")
    chief_j1 = register_user(email="chief.j1@uni.edu")
    chief_j2 = register_user(email="chief.j2@uni.edu")
    assigned_editor = register_user(email="assigned.ed@uni.edu")
    unassigned_editor = register_user(email="unassigned.ed@uni.edu")

    # Assign per-journal roles
    for journal_id, user_id, role in [
        (journal_1["id"], chief_j1["id"], "chief_editor"),
        (journal_2["id"], chief_j2["id"], "chief_editor"),
        (journal_1["id"], assigned_editor["id"], "handling_editor"),
        (journal_1["id"], unassigned_editor["id"], "handling_editor"),
    ]:
        assign = client.post(
            f"/api/v1/journals/{journal_id}/members",
            headers=admin_headers,
            json={"user_id": user_id, "role": role},
        )
        assert assign.status_code == 201, assign.text

    author_headers = auth_headers_for(email=author["email"])
    draft = client.post(
        "/api/v1/manuscripts",
        headers=author_headers,
        json={
            "journal_id": journal_1["id"],
            "title": "Confidential Draft Manuscript",
            "abstract": "Only authorized users may download this PDF.",
        },
    ).json()
    manuscript_id = draft["id"]

    pdf_bytes = _build_pdf_with_text("Confidential Scholarly Content v1")
    upload = client.post(
        f"/api/v1/manuscripts/{manuscript_id}/versions",
        headers=author_headers,
        files={"file": ("confidential.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload.status_code == 201

    # Assign handling editor on the manuscript row (workflow assignment endpoint arrives in Issue 04)
    manuscript_row = db_session.get(Manuscript, manuscript_id)
    assert manuscript_row is not None
    manuscript_row.assigned_editor_id = assigned_editor["id"]
    db_session.commit()

    download_url = f"/api/v1/manuscripts/{manuscript_id}/versions/1/download"

    # Authorized users: submitting author, System Admin, Journal 1 Chief Editor, assigned Handling Editor
    for label, headers in [
        ("submitting_author", author_headers),
        ("system_admin", admin_headers),
        ("journal_chief_editor", auth_headers_for(email=chief_j1["email"])),
        ("assigned_handling_editor", auth_headers_for(email=assigned_editor["email"])),
    ]:
        resp = client.get(download_url, headers=headers)
        assert resp.status_code == 200, f"Expected 200 for {label}, got {resp.status_code}: {resp.text}"
        assert resp.headers["content-type"] == "application/pdf"
        assert 'filename="confidential.pdf"' in resp.headers["content-disposition"]
        assert resp.content == pdf_bytes

    # Unauthenticated -> 401
    unauth = client.get(download_url)
    assert unauth.status_code == 401

    # Unauthorized users: another author, unassigned handling editor, Chief Editor of a different journal -> 403
    for label, headers in [
        ("other_author", auth_headers_for(email=other_author["email"])),
        ("unassigned_handling_editor", auth_headers_for(email=unassigned_editor["email"])),
        ("other_journal_chief_editor", auth_headers_for(email=chief_j2["email"])),
    ]:
        dl_resp = client.get(download_url, headers=headers)
        assert dl_resp.status_code == 403, f"Expected 403 for {label}, got {dl_resp.status_code}"
        assert dl_resp.json()["code"] == "manuscript_access_forbidden"

        detail_resp = client.get(f"/api/v1/manuscripts/{manuscript_id}", headers=headers)
        assert detail_resp.status_code == 403

        versions_resp = client.get(f"/api/v1/manuscripts/{manuscript_id}/versions", headers=headers)
        assert versions_resp.status_code == 403

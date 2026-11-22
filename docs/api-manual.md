# Developer & API Integration Manual

A practical reference for **Frontend**, **QA**, and **Backend** teammates integrating against the Scholarly Journal Publishing & Peer-Review Management API.

---

## 1. Base URL, Versioning & Health

| Purpose | URL (Local Dev) |
| --- | --- |
| API v1 Base URL | `http://127.0.0.1:8000/api/v1` |
| Health Check | `GET http://127.0.0.1:8000/health` |
| Swagger UI | `http://127.0.0.1:8000/docs` |
| OpenAPI Schema (JSON) | `http://127.0.0.1:8000/openapi.json` |

All API routes are strictly additive under `/api/v1/...`. CORS is pre-configured for `http://localhost:3000`, `http://localhost:5173`, `http://127.0.0.1:3000`, and `http://127.0.0.1:5173` (configurable via `CORS_ORIGINS` in `.env`).

---

## 2. Authentication (JWT Bearer Flow)

1. **Register** (`POST /api/v1/auth/register`): creates an active user account (returns `201 Created` with user profile).
2. **Login** (`POST /api/v1/auth/login`): exchange `email` + `password` for an `access_token` (default 30 min) and `refresh_token` (default 7 days).
3. **Authenticate requests**: send the access token in the `Authorization` header:
   ```http
   Authorization: Bearer <access_token>
   ```
4. **Refresh** (`POST /api/v1/auth/refresh`): exchange `{ "refresh_token": "<refresh_token>" }` for a fresh token pair when the access token expires. Access tokens cannot be used on `/refresh`, and deactivated accounts are rejected with `403 Forbidden`.

---

## 3. Structured Error Envelope & Status Codes

Every `4xx` and `5xx` response returns the same JSON envelope:

```json
{
  "code": "quality_gate_not_met",
  "message": "Acceptance quality gates are not satisfied for the current review round.",
  "details": {
    "manuscript_id": 4,
    "violations": [
      { "gate": "min_reviewers", "required": 2, "actual": 1, "review_round": 1 }
    ]
  }
}
```

| HTTP Status | Typical `code` | Meaning |
| --- | --- | --- |
| `400` | `bad_request`, `invalid_reviewer`, `revised_version_required`, `manuscript_version_required` | Business precondition failed on input |
| `401` | `unauthorized`, `invalid_credentials`, `invalid_token` | Missing, expired, or invalid JWT |
| `403` | `forbidden`, `journal_role_required`, `quality_gate_override_forbidden`, `manuscript_access_forbidden` | Authenticated user lacks required role or ownership |
| `404` | `not_found`, `manuscript_not_found`, `journal_not_found` | Resource does not exist |
| `409` | `conflict`, `invalid_status_transition`, `reviewer_conflict_of_interest`, `duplicate_review_invitation`, `quality_gate_not_met` | State conflict, duplicate, COI, or quality gate failure |
| `413` | `file_too_large` | Uploaded PDF exceeds `MAX_UPLOAD_SIZE_BYTES` (20 MB) |
| `415` | `invalid_file_type` | Uploaded file is not `application/pdf` |
| `422` | `validation_error` | Pydantic request schema validation failed |
| `500` | `internal_server_error` | Unhandled server error |

---

## 4. Pagination Contract

Collection endpoints accept `page` (1-based, default `1`) and `page_size` (`1..100`, default `20`) query parameters and return:

```json
{
  "page": 1,
  "page_size": 20,
  "total": 42,
  "items": [ ... ]
}
```

---

## 5. PDF Multipart Upload & Binary Download

- **Upload a manuscript version:** `POST /api/v1/manuscripts/{manuscript_id}/versions`
  - Content-Type: `multipart/form-data`
  - Fields:
    - `file`: required PDF (`application/pdf`, `%PDF-` signature, max 20 MB)
    - `response_to_reviewers`: optional text field (used when uploading revised `v2`, `v3`, ... in `revision_requested`)
  - Only the submitting author may upload, and only while status is `draft` or `revision_requested`.
- **Download a version PDF:** `GET /api/v1/manuscripts/{manuscript_id}/versions/{version_number}/download`
  - Returns raw `application/pdf` bytes with `Content-Disposition: attachment; filename="..."`.
  - Accessible to: Submitting Author, assigned Handling Editor, journal Chief Editor, System Admin, and Reviewers with an `accepted` or `completed` invitation (`pending`, `declined`, and uninvited users receive `403 Forbidden`).

---

## 6. Role-Based Access Matrix

| Endpoint Group | Public | Author (Owner) | Reviewer (Accepted) | Handling Editor (Assigned) | Chief Editor (Journal) | System Admin |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| `GET /journals`, `GET /journals/{id}` | Yes | Yes | Yes | Yes | Yes | Yes |
| `POST/PATCH /journals`, `GET/PATCH /admin/users` | No | No | No | No | No | Yes |
| `GET/PATCH /journals/{id}/workflow-config` | No | No | No | No | Yes | Yes |
| `GET/POST/DELETE /journals/{id}/members` | No | No | No | No | Yes | Yes |
| `GET /journals/{id}/manuscripts` | No | No | No | Yes (assigned only) | Yes | Yes |
| `POST /manuscripts`, `PATCH /manuscripts/{id}`, `POST /submit`, `POST /withdraw`, `POST /resubmit` | No | Yes | No | No | No | No |
| `GET /manuscripts/{id}`, `GET /versions`, `GET /versions/{v}/download` | No | Yes | Yes (masked if DA) | Yes | Yes | Yes |
| `POST /manuscripts/{id}/assign-editor` | No | No | No | No | Yes | Yes |
| `POST /desk-review`, `POST /desk-reject`, `POST /advance-to-review` | No | No | No | Yes | Yes | Yes |
| `POST/GET /manuscripts/{id}/invitations` | No | No | No | Yes | Yes | Yes |
| `GET /review-invitations`, `POST /accept`, `POST /decline`, `POST /review` | No | No | Invited reviewer only | No | No | No |
| `GET /manuscripts/{id}/reviews` | No | Masked (decided rounds only) | Own review only | Full unmasked | Full unmasked | Full unmasked |
| `POST /manuscripts/{id}/decisions` | No | No | No | Yes (no override) | Yes (+ override) | Yes (+ override) |
| `GET /manuscripts/{id}/decisions` | No | Yes | No | Yes | Yes | Yes |

---

## 7. Double-Anonymous Field Masking Rules

Frontend components must expect masked fields to be `null` (or `[]`) depending on the viewer's role and the journal's `anonymity_mode`:

### Manuscript Payload (`GET /api/v1/manuscripts/{id}`) viewed by an Accepted Reviewer

| Field | `double_anonymous` | `single_anonymous` | `open` |
| --- | --- | --- | --- |
| `submitter_id` | `null` | Author user ID | Author user ID |
| `co_authors` | `[]` | Full co-author list | Full co-author list |
| `versions[*].uploaded_by_id` | `null` | Uploader user ID | Uploader user ID |
| `status_history[*].changed_by_id` | `null` | Actor user ID | Actor user ID |

### Review Payload (`GET /api/v1/manuscripts/{id}/reviews`) viewed by the Submitting Author

| Field | `double_anonymous` | `single_anonymous` | `open` |
| --- | --- | --- | --- |
| `reviewer_label` | `"Reviewer #1"`, ... | `"Reviewer #1"`, ... | `"Reviewer #1"`, ... |
| `reviewer_id` | `null` | `null` | Reviewer user ID |
| `reviewer_name` / `reviewer_email` / `reviewer_affiliation` | `null` | `null` | Reviewer profile fields |
| `confidential_comments_to_editor` | **`null`** | **`null`** | **`null`** |

> **Important:** `confidential_comments_to_editor` is **never** returned to authors in any anonymity mode, and is never returned to other reviewers. Only the assigned Handling Editor, journal Chief Editor, System Admin, and the review's own author (when inspecting their own review) can see it.

---

## 8. End-to-End API Walkthrough

### Step 1: Login as Author (`author1@uni-delta.edu`)

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "author1@uni-delta.edu", "password": "DemoPassword123!"}'
```

### Step 2: Create a Draft, Upload PDF `v1`, and Submit

```bash
# 2a. Create draft
curl -X POST http://127.0.0.1:8000/api/v1/manuscripts \
  -H "Authorization: Bearer $AUTHOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "journal_id": 1,
    "title": "Fast Consensus in Edge Networks",
    "abstract": "We present a low-latency consensus protocol for edge clusters.",
    "keywords": ["consensus", "edge"],
    "co_authors": [
      {"full_name": "Dr. Hannah Brooks", "email": "author1@uni-delta.edu", "is_corresponding": true}
    ]
  }'

# 2b. Upload PDF v1
curl -X POST http://127.0.0.1:8000/api/v1/manuscripts/1/versions \
  -H "Authorization: Bearer $AUTHOR_TOKEN" \
  -F "file=@paper_v1.pdf;type=application/pdf"

# 2c. Submit manuscript (draft -> submitted)
curl -X POST http://127.0.0.1:8000/api/v1/manuscripts/1/submit \
  -H "Authorization: Bearer $AUTHOR_TOKEN"
```

### Step 3: Chief Editor Assigns Handling Editor & Editor Advances to Peer Review

```bash
# Chief Editor assigns Handling Editor
curl -X POST http://127.0.0.1:8000/api/v1/manuscripts/1/assign-editor \
  -H "Authorization: Bearer $CHIEF_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"editor_id": 4}'

# Handling Editor starts desk review and advances to under_review (round 1)
curl -X POST http://127.0.0.1:8000/api/v1/manuscripts/1/desk-review \
  -H "Authorization: Bearer $EDITOR_TOKEN"

curl -X POST http://127.0.0.1:8000/api/v1/manuscripts/1/advance-to-review \
  -H "Authorization: Bearer $EDITOR_TOKEN"
```

### Step 4: Invite Reviewer, Accept, Inspect Masked Manuscript, Submit Review

```bash
# Invite reviewer
curl -X POST http://127.0.0.1:8000/api/v1/manuscripts/1/invitations \
  -H "Authorization: Bearer $EDITOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reviewer_id": 6}'

# Reviewer accepts invitation
curl -X POST http://127.0.0.1:8000/api/v1/review-invitations/1/accept \
  -H "Authorization: Bearer $REVIEWER_TOKEN"

# Reviewer fetches manuscript (submitter_id=null, co_authors=[] in double_anonymous)
curl http://127.0.0.1:8000/api/v1/manuscripts/1 \
  -H "Authorization: Bearer $REVIEWER_TOKEN"

# Reviewer submits structured review
curl -X POST http://127.0.0.1:8000/api/v1/review-invitations/1/review \
  -H "Authorization: Bearer $REVIEWER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "originality_score": 5,
    "methodology_score": 4,
    "clarity_score": 4,
    "significance_score": 5,
    "recommendation": "minor_revision",
    "comments_to_author": "Strong results; please expand Section 4.",
    "confidential_comments_to_editor": "Recommend minor revision."
  }'
```

### Step 5: Editorial Decision, Revision Upload `v2`, and Resubmission

```bash
# Issue major_revision decision
curl -X POST http://127.0.0.1:8000/api/v1/manuscripts/1/decisions \
  -H "Authorization: Bearer $EDITOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"decision": "major_revision", "decision_letter": "Please address reviewer comments."}'

# Author uploads revised PDF v2 with response_to_reviewers
curl -X POST http://127.0.0.1:8000/api/v1/manuscripts/1/versions \
  -H "Authorization: Bearer $AUTHOR_TOKEN" \
  -F "file=@paper_v2.pdf;type=application/pdf" \
  -F "response_to_reviewers=Expanded Section 4 with additional benchmarks."

# Author resubmits into review round 2
curl -X POST http://127.0.0.1:8000/api/v1/manuscripts/1/resubmit \
  -H "Authorization: Bearer $AUTHOR_TOKEN"
```

---

## 9. Importing into Postman or Insomnia

1. Start the backend locally (`uvicorn app.main:app --reload`).
2. In **Postman**: click **Import** → paste `http://127.0.0.1:8000/openapi.json` → select **OpenAPI 3.1** → **Import**.
3. In **Insomnia**: click **Create → Import From → URL** → enter `http://127.0.0.1:8000/openapi.json`.
4. Configure a collection-level Bearer token variable (`{{access_token}}`) populated from `POST /api/v1/auth/login`.

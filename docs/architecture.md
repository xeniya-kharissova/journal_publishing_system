# System Architecture & Diagrams

This document describes the layered modular architecture, relational data model, workflow state machine, and double-anonymous peer-review protocol of the Scholarly Journal Publishing & Peer-Review Management Backend.

---

## 1. Layered Modular Architecture

The backend separates HTTP transport, domain logic, persistence, and swappable external integrations into four strict layers:

```mermaid
flowchart TD
    Client["Frontend / QA / API Clients"] --> Router["API / Router Layer (app/api/v1/)<br/>FastAPI routes, Pydantic v2 schemas, JWT & RBAC deps"]
    Router --> Service["Service Layer (app/services/)<br/>Workflow state machine, anonymity projection, quality gates, COI checks"]
    Service --> Models["Data / ORM Layer (app/models/ + alembic/)<br/>SQLAlchemy 2.0 entities, FK & unique constraints, migrations"]
    Service --> Adapters["Adapter Layer (app/adapters/)<br/>Swappable interfaces: StorageAdapter (and Email/Plagiarism/ORCID in Weeks 2-3)"]
    Models --> DB[("SQLite (default) or PostgreSQL<br/>via DATABASE_URL")]
    Adapters --> FS["Local Filesystem Storage (./storage)"]
```

- **API / Router Layer (`app/api/v1/`, `app/api/deps.py`, `app/schemas/`):** Handles HTTP routing, request validation, pagination, Bearer JWT extraction, per-journal RBAC dependencies, and structured JSON error envelopes. Never contains raw business rules.
- **Service Layer (`app/services/`):** Owns all business invariants — centralized state-machine transitions (`workflow_service.py`), role- and anonymity-aware DTO projection (`manuscript_service.py`, `review_service.py`), conflict-of-interest checks, and acceptance quality gates (`decision_service.py`).
- **Data / ORM Layer (`app/models/`, `alembic/versions/`):** Declarative SQLAlchemy 2.0 models with explicit foreign keys, unique constraints, check constraints, and portable Alembic migrations.
- **Adapter Layer (`app/adapters/`):** Abstract interfaces with zero-cost local defaults (`LocalFilesystemStorageAdapter`, plus upcoming `EmailAdapter`, `PlagiarismProvider`, and `OrcidClient`) cleanly overridable in `pytest` via FastAPI dependency overrides.

---

## 2. Entity-Relationship Diagram (ERD)

Matches the live Alembic schema through revision `0006_create_editorial_decisions`:

```mermaid
erDiagram
    users {
        int id PK
        string email UK
        string password_hash
        string full_name
        string affiliation
        string orcid
        json expertise_keywords
        int max_active_reviews
        bool is_system_admin
        bool is_active
    }

    journals {
        int id PK
        string title
        string slug UK
        string issn
        string doi_prefix
        bool apc_enabled
        int apc_amount_cents
        string apc_currency
        bool is_active
    }

    journal_workflow_configs {
        int id PK
        int journal_id FK,UK
        string anonymity_mode
        int min_reviewers
        bool require_desk_review
        bool require_plagiarism_check
        int desk_review_sla_days
        int review_sla_days
        int decision_sla_days
        int revision_sla_days
    }

    journal_memberships {
        int id PK
        int journal_id FK
        int user_id FK
        string role
        int assigned_by_id FK
    }

    manuscripts {
        int id PK
        int journal_id FK
        int submitter_id FK
        int assigned_editor_id FK
        string title
        text abstract
        string status
        int current_version_number
        int current_review_round
        datetime stage_entered_at
        datetime submitted_at
        datetime decided_at
        datetime published_at
        string doi UK
    }

    manuscript_authors {
        int id PK
        int manuscript_id FK
        int author_order
        string full_name
        string email
        string affiliation
        string orcid
        bool is_corresponding
        int user_id FK
    }

    manuscript_versions {
        int id PK
        int manuscript_id FK
        int version_number
        string file_key UK
        string original_filename
        int file_size_bytes
        text extracted_text
        text response_to_reviewers
        int uploaded_by_id FK
    }

    manuscript_status_history {
        int id PK
        int manuscript_id FK
        string from_status
        string to_status
        int changed_by_id FK
        text note
        datetime created_at
    }

    review_invitations {
        int id PK
        int manuscript_id FK
        int reviewer_id FK
        int review_round
        string status
        int invited_by_id FK
        datetime due_at
        datetime responded_at
        text decline_reason
    }

    reviews {
        int id PK
        int invitation_id FK,UK
        int manuscript_id FK
        int manuscript_version_id FK
        int reviewer_id FK
        int review_round
        int originality_score
        int methodology_score
        int clarity_score
        int significance_score
        string recommendation
        text comments_to_author
        text confidential_comments_to_editor
    }

    editorial_decisions {
        int id PK
        int manuscript_id FK
        int review_round
        int manuscript_version_number
        int decided_by_id FK
        string decision
        text decision_letter
        text override_reason
    }

    journals ||--|| journal_workflow_configs : "has config"
    journals ||--o{ journal_memberships : "has members"
    users ||--o{ journal_memberships : "holds roles"
    journals ||--o{ manuscripts : "receives"
    users ||--o{ manuscripts : "submits / handles"
    manuscripts ||--o{ manuscript_authors : "has co-authors"
    manuscripts ||--o{ manuscript_versions : "has versions"
    manuscripts ||--o{ manuscript_status_history : "logs transitions"
    manuscripts ||--o{ review_invitations : "has invitations"
    users ||--o{ review_invitations : "invited as reviewer"
    review_invitations ||--o| reviews : "produces"
    manuscript_versions ||--o{ reviews : "evaluated on"
    manuscripts ||--o{ editorial_decisions : "has decisions"
```

---

## 3. Editorial Workflow State Machine

All transitions are enforced centrally by `app/services/workflow_service.py` and logged immutably to `manuscript_status_history`:

```mermaid
stateDiagram-v2
    [*] --> draft
    draft --> submitted : author submits (requires v1 PDF)
    draft --> withdrawn : author withdraws

    submitted --> desk_review : editor starts desk review
    submitted --> under_review : editor advances (only if require_desk_review=false)
    submitted --> withdrawn : author withdraws

    desk_review --> under_review : editor advances (sets round=1)
    desk_review --> rejected : editor desk-rejects (rationale required)
    desk_review --> withdrawn : author withdraws

    under_review --> revision_requested : decision minor_revision / major_revision
    under_review --> accepted : decision accept (min_reviewers gate or Chief override)
    under_review --> rejected : decision reject
    under_review --> withdrawn : author withdraws

    revision_requested --> under_review : author uploads newer PDF & resubmits (round += 1)
    revision_requested --> withdrawn : author withdraws

    accepted --> production : editor moves to production
    accepted --> withdrawn : author withdraws

    production --> published : editor publishes article

    rejected --> [*]
    withdrawn --> [*]
    published --> [*]
```

---

## 4. Double-Anonymous Peer-Review Sequence

Illustrates server-side identity masking when `anonymity_mode == double_anonymous`:

```mermaid
sequenceDiagram
    actor Editor as Handling Editor
    actor Reviewer as Invited Reviewer
    actor Author as Submitting Author
    participant API as FastAPI + Service Layer
    participant DB as Relational DB

    Editor->>API: POST /manuscripts/{id}/invitations (reviewer_id)
    API->>DB: Verify reviewer role, COI (not author/co-author), no duplicate
    API-->>Editor: 201 ReviewInvitation (status=pending)

    Reviewer->>API: POST /review-invitations/{inv_id}/accept
    API->>DB: Transition invitation pending -> accepted
    API-->>Reviewer: 200 ReviewInvitation (status=accepted)

    Reviewer->>API: GET /manuscripts/{id}
    API->>DB: Load manuscript + workflow_config (double_anonymous)
    API-->>Reviewer: 200 ManuscriptResponse (submitter_id=null, co_authors=[])

    Reviewer->>API: POST /review-invitations/{inv_id}/review (scores, comments_to_author, confidential_comments_to_editor)
    API->>DB: Persist Review & mark invitation completed
    API-->>Reviewer: 201 ReviewResponse

    Author->>API: GET /manuscripts/{id}/reviews
    API->>DB: Load reviews + workflow_config (double_anonymous)
    API-->>Author: 200 [ReviewResponse(reviewer_label="Reviewer #1", reviewer_id=null, reviewer_name=null, confidential_comments_to_editor=null)]

    Editor->>API: GET /manuscripts/{id}/reviews
    API->>DB: Load reviews (editorial viewer role)
    API-->>Editor: 200 [ReviewResponse(reviewer_id, reviewer_name, confidential_comments_to_editor)]
```

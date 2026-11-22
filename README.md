# Scholarly Journal Publishing & Peer-Review Management Backend

An autonomous, modular REST API and relational database backend for an **Integrated Scholarly Journal Publishing and Peer-Review Management System** (SFWE343 — Software Analysis and Design, Topic 2).

Built with **Python 3.11+**, **FastAPI**, **Pydantic v2**, **SQLAlchemy 2.0**, and **Alembic**, running locally out of the box on **SQLite** with zero container setup while remaining 100% **PostgreSQL-compatible** via a single `DATABASE_URL` environment variable.

## Key Capabilities (Week 1 Core)

- **Identity, JWT Auth & Profiles:** Argon2 password hashing, JWT access/refresh tokens, user profiles with ORCID, expertise keywords, review capacity, and System Admin account controls.
- **Multi-Journal Management & Per-Journal RBAC:** Multiple independent journals on one platform with per-journal roles (`chief_editor`, `handling_editor`, `reviewer`, `author`) and configurable editorial workflow policies (`anonymity_mode`, `min_reviewers`, `require_desk_review`, `require_plagiarism_check`, SLA deadlines, optional APC config).
- **Manuscript Submissions & Versioned PDF Storage:** Ordered co-authors, sequential immutable PDF versions (`v1`, `v2`, ...) with local text extraction (`pypdf`), sanitized storage via `StorageAdapter`, and role-enforced downloads.
- **Editorial Workflow State Machine & Audit History:** Centralized validated transitions (`draft -> submitted -> desk_review -> under_review -> revision_requested -> accepted -> production -> published` plus `rejected` / `withdrawn`) with an immutable `manuscript_status_history` audit trail.
- **Peer Review & Strict Server-Side Anonymity Masking:** Invitation lifecycle (`pending`, `accepted`, `declined`, `completed`), self/co-author conflict-of-interest blocking, structured 1–5 scoring, and server-side masking across `double_anonymous`, `single_anonymous`, and `open` modes.
- **Editorial Decisions, Quality Gates & Multi-Round Revisions:** Formal decisions (`accept`, `minor_revision`, `major_revision`, `reject`), `min_reviewers` quality gate with audited Chief Editor overrides, and revised PDF resubmission into subsequent review rounds.

## Quickstart

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
python -m scripts.seed_demo
uvicorn app.main:app --reload
```

### macOS / Linux (POSIX)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
python -m scripts.seed_demo
uvicorn app.main:app --reload
```

Once running:
- **Interactive Swagger UI:** http://127.0.0.1:8000/docs
- **ReDoc:** http://127.0.0.1:8000/redoc
- **OpenAPI JSON (for Postman/Insomnia):** http://127.0.0.1:8000/openapi.json
- **Health Check:** http://127.0.0.1:8000/health

## Running Tests

```powershell
pytest
```

The test suite runs against an isolated temporary SQLite database initialized via the real Alembic migrations (`alembic upgrade head`) and exercises the full HTTP API boundary (`/api/v1/...`) with zero ORM mocking.

## Switching to PostgreSQL

No code or migration changes are required. Install `psycopg[binary]` (or `psycopg2-binary`) and set `DATABASE_URL` in `.env`:

```env
DATABASE_URL="postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require"
```

Then run:

```bash
alembic upgrade head
python -m scripts.seed_demo
```

## Seeded Demo Accounts

Running `python -m scripts.seed_demo` is **idempotent** (safe to run repeatedly without duplicating records). All seeded accounts share the demo password:

> **Password:** `DemoPassword123!`

| Email | Name | Platform / Journal Roles |
| --- | --- | --- |
| `admin@journal-platform.org` | Dr. Elena Vance | **System Admin** |
| `chief.cs@journal-platform.org` | Prof. Marcus Sterling | `chief_editor` in `jcs-research` (double-anonymous) |
| `editor.cs@journal-platform.org` | Dr. David Chen | `handling_editor` in `jcs-research` |
| `chief.bio@journal-platform.org` | Prof. Claire Moreau | `chief_editor` in `open-bio-data` (open review) |
| `editor.bio@journal-platform.org` | Dr. Sofia Alvarez | `handling_editor` in `open-bio-data` |
| `reviewer1@uni-alpha.edu` | Prof. Liam O'Connor | `reviewer` in `jcs-research` & `open-bio-data` |
| `reviewer2@uni-beta.edu` | Dr. Priya Patel | `reviewer` in `jcs-research` |
| `reviewer3@uni-gamma.edu` | Dr. Henrik Lindholm | `reviewer` in `open-bio-data` |
| `author1@uni-delta.edu` | Dr. Hannah Brooks | `author` in `jcs-research` (owns draft, submitted, under_review, revision_requested manuscripts) |
| `author2@uni-epsilon.edu` | Dr. Kenji Takahashi | `author` in `open-bio-data` (owns accepted manuscript) |

## Documentation

- [Domain Glossary](GLOSSARY.md) — Canonical scholarly publishing vocabulary.
- [Developer & API Integration Manual](docs/api-manual.md) — Auth, error envelope, pagination, RBAC matrix, double-anonymous masking contract, and end-to-end walkthroughs for frontend & QA teammates.
- [System Architecture & Diagrams](docs/architecture.md) — Layered architecture, Mermaid ERD, workflow state machine, and double-anonymous sequence diagram.
- [Requirements Traceability](docs/requirements-traceability.md) — Mapping of SFWE343 Topic 2 requirements to endpoints and automated tests.
- [Architecture Decision Records](docs/adr/) — Concise records documenting key design choices.

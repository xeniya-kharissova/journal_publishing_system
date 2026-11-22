# ADR-0001: Layered Modular FastAPI Architecture with Portable SQLAlchemy 2.0 + Alembic

- **Status:** Accepted
- **Date:** 2026-11-22

## Context
The SFWE343 Topic 2 backend must support a rich relational domain (multi-journal RBAC, versioned manuscripts, peer review, editorial decisions, publishing, analytics) while remaining easy for teammates to run locally with zero container overhead and deployable to cloud PostgreSQL without rewrites.

## Decision
Organize the codebase into four strict layers:
1. **API / Router (`app/api/v1/`, `app/schemas/`):** HTTP routing, Pydantic v2 validation, OpenAPI metadata, and auth/RBAC dependencies.
2. **Service (`app/services/`):** Domain orchestration, workflow state machine, anonymity projection, COI checks, and quality gates.
3. **Data / ORM (`app/models/`, `alembic/`):** SQLAlchemy 2.0 declarative models with explicit foreign keys, unique/check constraints, and portable Alembic migrations.
4. **Adapter (`app/adapters/`):** Abstract interfaces for swappable I/O boundaries (file storage, email, plagiarism, ORCID).

SQLite is the default local database (with `PRAGMA foreign_keys=ON` enforced per connection), while avoiding SQLite-only or PostgreSQL-only schema features so switching `DATABASE_URL` to PostgreSQL works immediately.

## Consequences
- Frontend and QA teammates start the full stack locally in one command without Docker.
- Business rules are testable through a single high-level HTTP API seam against real Alembic-migrated databases.
- Adding Weeks 2–6 features stays strictly additive inside new routers, services, models, and migrations.

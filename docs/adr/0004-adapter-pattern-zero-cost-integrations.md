# ADR-0004: Adapter Pattern for Zero-Cost Local Integrations

- **Status:** Accepted
- **Date:** 2026-11-22

## Context
A scholarly publishing platform interacts with external boundaries: file storage, outbound email, plagiarism screening, and ORCID verification. Academic coursework requires $0 operating cost and deterministic offline tests, while preserving clean architecture for production swap-ins.

## Decision
Define thin abstract adapter interfaces under `app/adapters/` with zero-cost local defaults injected via FastAPI dependencies:
- `StorageAdapter` → `LocalFilesystemStorageAdapter` (Week 1; prevents path traversal, validates PDF MIME/signature/size).
- `EmailAdapter` → database/console audit logger with optional SMTP via env vars (Week 2).
- `PlagiarismProvider` → deterministic local TF-IDF / n-gram similarity engine over locally extracted PDF text (Week 2).
- `OrcidClient` → local ISO 7064 mod 11-2 checksum validation + optional public ORCID API lookup (Week 3).

## Consequences
- Zero paid API keys or third-party cloud accounts required to run or grade the project.
- Automated `pytest` tests swap only the adapter boundary (e.g., `tmp_path` storage) while running the entire real FastAPI + SQLAlchemy + Alembic stack.

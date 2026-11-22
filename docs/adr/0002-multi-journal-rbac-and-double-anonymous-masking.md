# ADR-0002: Per-Journal RBAC & Server-Side Double-Anonymous Response Projection

- **Status:** Accepted
- **Date:** 2026-11-22

## Context
On a multi-journal platform, the same researcher frequently acts as an `author` in one journal and a `reviewer` or `handling_editor` in another. Moreover, double-anonymous peer review is a security invariant: hiding author or reviewer identities solely in the frontend UI would expose sensitive identities and confidential editor notes in raw network payloads.

## Decision
1. Store roles per journal in a `journal_memberships(journal_id, user_id, role)` join table (plus a global `User.is_system_admin` flag), enforced via reusable FastAPI dependencies (`require_journal_roles`) and manuscript-level access helpers.
2. Enforce identity masking **strictly on the server** inside service-layer DTO projections (`project_manuscript_for_user`, `project_versions_for_user`, `project_review_for_viewer`) driven by `JournalWorkflowConfig.anonymity_mode`:
   - In `double_anonymous`, reviewers receive `submitter_id=null`, `co_authors=[]`, `uploaded_by_id=null`, `changed_by_id=null`; authors receive deterministic anonymous labels (`"Reviewer #1"`) with `reviewer_id=null`, profile fields `null`, and `confidential_comments_to_editor=null`.
   - In `single_anonymous`, reviewers see authors while authors still see anonymous reviewers and no confidential notes.
   - In `open`, both see identities while `confidential_comments_to_editor` remains restricted to editors and System Admins.

## Consequences
- Zero identity or confidential-comment leakage in raw HTTP JSON responses, verified by negative security tests across all three modes.
- Frontend clients render directly from the API contract without needing security-sensitive client-side filtering.

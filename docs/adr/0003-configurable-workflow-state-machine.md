# ADR-0003: Centralized Configurable Editorial Workflow State Machine

- **Status:** Accepted
- **Date:** 2026-11-22

## Context
Manuscripts move through a strict scholarly lifecycle (`draft -> submitted -> desk_review -> under_review -> revision_requested -> accepted -> production -> published`, plus `rejected` and `withdrawn`), while individual journals need policy flexibility (such as skipping desk review, setting minimum reviewer counts, and allowing audited Chief Editor overrides).

## Decision
1. Centralize all status transitions in `workflow_service.transition_manuscript_status(...)`, backed by an explicit transition graph parameterized by `JournalWorkflowConfig.require_desk_review`.
2. Reject every invalid transition or mutation from terminal states (`rejected`, `withdrawn`, `published`) with `409 Conflict`.
3. Automatically append an immutable `ManuscriptStatusHistory` row (`from_status`, `to_status`, `changed_by_id`, `note`, `created_at`) and update lifecycle timestamps (`stage_entered_at`, `submitted_at`, `decided_at`, `published_at`) and `current_review_round` atomically within the same database transaction.

## Consequences
- Invalid workflow jumps are impossible from any endpoint.
- Every editorial action and Chief Editor quality-gate override has a permanent, queryable audit trail.
- SLA monitoring and analytics (Weeks 4–6) can rely on accurate `stage_entered_at`, `submitted_at`, and `decided_at` timestamps.

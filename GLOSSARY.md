# Domain Glossary

Canonical domain vocabulary used consistently across the REST API (`/api/v1`), Pydantic schemas, SQLAlchemy ORM models, Alembic migrations, and documentation.

---

## Core Entities & Concepts

### Journal
An independent scholarly publication hosted on the platform (e.g., *Journal of Computing Systems*). Identified by a unique URL-safe `slug` and optional `ISSN`. Each journal maintains its own editorial board, per-journal RBAC memberships, workflow configuration, DOI prefix, and optional APC fee policy.

### JournalMembership
A per-journal role assignment linking a `User` to a specific `Journal` with one of four roles: `chief_editor`, `handling_editor`, `reviewer`, or `author`. A single user can hold different roles across different journals (and multiple roles within one journal, subject to per-manuscript conflict-of-interest checks).

### JournalWorkflowConfig
A 1-to-1 configuration attached to each `Journal` governing editorial rules:
- `anonymity_mode`: `double_anonymous`, `single_anonymous`, or `open`.
- `min_reviewers`: minimum completed reviews required in the current round before an `accept` decision can be issued.
- `require_desk_review`: whether submitted manuscripts must pass through `desk_review` before entering `under_review`.
- `require_plagiarism_check`: whether a plagiarism report is required before acceptance.
- SLA thresholds in days (`desk_review_sla_days`, `review_sla_days`, `decision_sla_days`, `revision_sla_days`).

### Manuscript
A scholarly paper submitted by a registered user (`submitter_id`) to a specific `Journal`. Tracks metadata (`title`, `abstract`, `keywords`, `subject_area`), ordered co-authors (`ManuscriptAuthor`), workflow `status`, `assigned_editor_id`, `current_version_number`, `current_review_round`, and lifecycle timestamps (`stage_entered_at`, `submitted_at`, `decided_at`, `published_at`).

### ManuscriptVersion
An immutable uploaded PDF revision (`v1`, `v2`, `v3`, ...) belonging to a `Manuscript`. Stores the sanitized original filename, storage key, byte size, locally extracted plain text (`extracted_text`), and an optional `response_to_reviewers` letter for revised uploads. Earlier versions are never overwritten.

### ManuscriptStatusHistory
An append-only audit trail recording every validated workflow state transition (`from_status`, `to_status`, `changed_by_id`, `note`, `created_at`) on a `Manuscript`.

### ReviewRound
A 1-based integer counter (`current_review_round`) representing a distinct cycle of external peer review on a `Manuscript`. Initial advancement into `under_review` sets round `1`; each subsequent author revision resubmission (`revision_requested -> under_review`) increments the round (`2`, `3`, ...).

### ReviewInvitation
An invitation issued by an assigned Handling Editor, Chief Editor, or System Admin asking a user with the `reviewer` role in that journal to evaluate a `Manuscript` for a specific `ReviewRound` by a `due_at` deadline. Lifecycle states: `pending`, `accepted`, `declined`, `completed`, `expired`.

### Review
A structured peer-review evaluation submitted once per accepted `ReviewInvitation`. Captures four 1–5 numeric criteria scores (`originality_score`, `methodology_score`, `clarity_score`, `significance_score`), an overall `recommendation` (`accept`, `minor_revision`, `major_revision`, `reject`), author-facing `comments_to_author`, and editor-only `confidential_comments_to_editor`.

### Double-Anonymous Review (and Anonymity Modes)
Server-side identity-masking policy enforced on API responses based on `JournalWorkflowConfig.anonymity_mode`:
- **`double_anonymous`:** Reviewers do not see author identities (`submitter_id`, `co_authors`, `uploaded_by_id`, `changed_by_id` are stripped); authors do not see reviewer identities or confidential editor comments (only anonymous labels such as `"Reviewer #1"`).
- **`single_anonymous`:** Reviewers see author identities; authors still cannot see reviewer identities or confidential editor comments.
- **`open`:** Both reviewers and authors see each other's identities; `confidential_comments_to_editor` remains strictly restricted to editors and System Admins.

### EditorialDecision
A formal editorial outcome (`accept`, `minor_revision`, `major_revision`, `reject`) recorded once per `(manuscript_id, review_round)` with a `decision_letter` and optional `override_reason`. Drives the workflow transition out of `under_review` to `accepted`, `revision_requested`, or `rejected`.

### Quality Gate & Chief Editor Override
Automated policy checks enforced when issuing an `accept` decision (such as `min_reviewers` completed reviews in the current round, and plagiarism screening when enabled). A `handling_editor` cannot bypass a failed gate (`409 Conflict` / `403 Forbidden`); a `chief_editor` (or `System Admin`) may explicitly override it by supplying a non-empty `override_reason` that is permanently audited on both the `EditorialDecision` and `ManuscriptStatusHistory`.

### DOI (Digital Object Identifier)
A persistent, unique citation identifier minted automatically upon article publication in the format `{journal.doi_prefix}/{journal.slug}.{year}.{manuscript.id}`.

### ORCID (Open Researcher and Contributor iD)
A standardized 16-digit researcher identifier (`0000-0000-0000-000X`) validated with the ISO 7064 mod 11-2 checksum to disambiguate authors and reviewers.

### APC (Article Processing Charge)
An optional publication fee configured per journal (`apc_enabled`, `apc_amount_cents`, `apc_currency`) billed to accepted articles when enabled, supporting simulated payment and waiver workflows.

### SLA (Service-Level Agreement)
Per-stage editorial turnaround targets (in days) defined on `JournalWorkflowConfig` (`desk_review_sla_days`, `review_sla_days`, `decision_sla_days`, `revision_sla_days`) used to set default review deadlines and monitor workflow delays.

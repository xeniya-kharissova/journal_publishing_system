"""Idempotent CLI script populating realistic demo data for local dev, frontend, and QA.

Usage:
    python -m scripts.seed_demo
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import io
from pathlib import Path

from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.storage import LocalFilesystemStorageAdapter, StorageAdapter
from app.core.config import get_settings
from app.core.database import create_db_engine, create_session_factory
from app.core.security import hash_password
from app.models.decision import EditorialDecision, EditorialDecisionType
from app.models.journal import (
    AnonymityMode,
    Journal,
    JournalMembership,
    JournalRole,
    JournalWorkflowConfig,
)
from app.models.manuscript import (
    Manuscript,
    ManuscriptAuthor,
    ManuscriptStatus,
    ManuscriptStatusHistory,
    ManuscriptVersion,
)
from app.models.review import (
    Review,
    ReviewInvitation,
    ReviewInvitationStatus,
    ReviewRecommendation,
)
from app.models.user import User

DEMO_PASSWORD = "DemoPassword123!"


@dataclass(frozen=True)
class SeedSummary:
    """Counts of canonical demo entities present after seeding."""

    users: int
    journals: int
    memberships: int
    manuscripts: int
    versions: int
    invitations: int
    reviews: int
    decisions: int


def _make_sample_pdf(label: str) -> bytes:
    """Create a valid minimal PDF byte stream with embedded metadata."""
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": label, "/Producer": "Scholarly Journal Demo Seeder"})
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _get_or_create_user(
    db: Session,
    *,
    email: str,
    full_name: str,
    affiliation: str,
    orcid: str | None = None,
    expertise_keywords: list[str] | None = None,
    is_system_admin: bool = False,
) -> User:
    existing = db.scalar(select(User).where(User.email == email.lower()))
    if existing is not None:
        return existing

    user = User(
        email=email.lower(),
        password_hash=hash_password(DEMO_PASSWORD),
        full_name=full_name,
        affiliation=affiliation,
        bio=f"Demo account for {full_name} ({affiliation}).",
        orcid=orcid,
        expertise_keywords=expertise_keywords or [],
        max_active_reviews=5,
        is_system_admin=is_system_admin,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _get_or_create_journal(
    db: Session,
    *,
    slug: str,
    title: str,
    issn: str,
    description: str,
    scope_keywords: list[str],
    publisher_name: str,
    doi_prefix: str,
    anonymity_mode: AnonymityMode,
    min_reviewers: int,
    require_desk_review: bool,
    apc_enabled: bool = False,
    apc_amount_cents: int = 0,
    apc_currency: str = "USD",
) -> Journal:
    existing = db.scalar(select(Journal).where(Journal.slug == slug))
    if existing is not None:
        return existing

    journal = Journal(
        title=title,
        slug=slug,
        issn=issn,
        description=description,
        scope_keywords=scope_keywords,
        publisher_name=publisher_name,
        doi_prefix=doi_prefix,
        apc_enabled=apc_enabled,
        apc_amount_cents=apc_amount_cents,
        apc_currency=apc_currency,
        is_active=True,
    )
    journal.workflow_config = JournalWorkflowConfig(
        anonymity_mode=anonymity_mode.value,
        min_reviewers=min_reviewers,
        require_desk_review=require_desk_review,
        require_plagiarism_check=False,
        desk_review_sla_days=7,
        review_sla_days=21,
        decision_sla_days=14,
        revision_sla_days=30,
    )
    db.add(journal)
    db.flush()
    return journal


def _ensure_membership(
    db: Session,
    *,
    journal: Journal,
    user: User,
    role: JournalRole,
    assigned_by: User,
) -> JournalMembership:
    existing = db.scalar(
        select(JournalMembership).where(
            JournalMembership.journal_id == journal.id,
            JournalMembership.user_id == user.id,
            JournalMembership.role == role.value,
        )
    )
    if existing is not None:
        return existing

    membership = JournalMembership(
        journal_id=journal.id,
        user_id=user.id,
        role=role.value,
        assigned_by_id=assigned_by.id,
    )
    db.add(membership)
    db.flush()
    return membership


def _get_or_create_manuscript(
    db: Session,
    storage: StorageAdapter,
    *,
    journal: Journal,
    submitter: User,
    assigned_editor: User | None,
    title: str,
    abstract: str,
    keywords: list[str],
    subject_area: str,
    status: ManuscriptStatus,
    current_review_round: int,
    co_authors_data: list[dict],
    transitions: list[tuple[ManuscriptStatus, ManuscriptStatus, User, str]],
    pdf_filename: str,
    extracted_text: str,
    now: datetime,
) -> tuple[Manuscript, ManuscriptVersion]:
    existing = db.scalar(
        select(Manuscript).where(
            Manuscript.journal_id == journal.id,
            Manuscript.title == title,
        )
    )
    if existing is not None:
        version = db.scalar(
            select(ManuscriptVersion).where(
                ManuscriptVersion.manuscript_id == existing.id,
                ManuscriptVersion.version_number == 1,
            )
        )
        assert version is not None
        return existing, version

    submitted_at = (
        now - timedelta(days=10) if status != ManuscriptStatus.DRAFT else None
    )
    decided_at = (
        now - timedelta(days=2)
        if status
        in {
            ManuscriptStatus.REVISION_REQUESTED,
            ManuscriptStatus.ACCEPTED,
            ManuscriptStatus.REJECTED,
        }
        else None
    )

    manuscript = Manuscript(
        journal_id=journal.id,
        submitter_id=submitter.id,
        assigned_editor_id=assigned_editor.id if assigned_editor else None,
        title=title,
        abstract=abstract,
        keywords=keywords,
        subject_area=subject_area,
        status=status.value,
        current_version_number=1,
        current_review_round=current_review_round,
        stage_entered_at=now - timedelta(days=1),
        submitted_at=submitted_at,
        decided_at=decided_at,
    )
    manuscript.co_authors = [
        ManuscriptAuthor(
            author_order=idx,
            full_name=ca["full_name"],
            email=ca["email"],
            affiliation=ca.get("affiliation"),
            orcid=ca.get("orcid"),
            is_corresponding=ca.get("is_corresponding", False),
            user_id=ca.get("user_id"),
        )
        for idx, ca in enumerate(co_authors_data, start=1)
    ]
    db.add(manuscript)
    db.flush()

    pdf_bytes = _make_sample_pdf(title)
    file_key = f"manuscripts/{manuscript.id}/v1_demo.pdf"
    canonical_key = storage.save_file(file_key, pdf_bytes)

    version = ManuscriptVersion(
        manuscript_id=manuscript.id,
        version_number=1,
        file_key=canonical_key,
        original_filename=pdf_filename,
        content_type="application/pdf",
        file_size_bytes=len(pdf_bytes),
        extracted_text=extracted_text,
        uploaded_by_id=submitter.id,
    )
    db.add(version)

    for offset, (from_st, to_st, actor, note) in enumerate(transitions, start=1):
        db.add(
            ManuscriptStatusHistory(
                manuscript_id=manuscript.id,
                from_status=from_st.value,
                to_status=to_st.value,
                changed_by_id=actor.id,
                note=note,
                created_at=now - timedelta(days=max(1, 12 - offset * 2)),
            )
        )

    db.flush()
    return manuscript, version


def _ensure_invitation(
    db: Session,
    *,
    manuscript: Manuscript,
    reviewer: User,
    invited_by: User,
    review_round: int,
    status: ReviewInvitationStatus,
    due_at: datetime,
    responded_at: datetime | None = None,
) -> ReviewInvitation:
    existing = db.scalar(
        select(ReviewInvitation).where(
            ReviewInvitation.manuscript_id == manuscript.id,
            ReviewInvitation.reviewer_id == reviewer.id,
            ReviewInvitation.review_round == review_round,
        )
    )
    if existing is not None:
        return existing

    invitation = ReviewInvitation(
        manuscript_id=manuscript.id,
        reviewer_id=reviewer.id,
        review_round=review_round,
        status=status.value,
        invited_by_id=invited_by.id,
        due_at=due_at,
        responded_at=responded_at,
    )
    db.add(invitation)
    db.flush()
    return invitation


def _ensure_review(
    db: Session,
    *,
    invitation: ReviewInvitation,
    manuscript: Manuscript,
    version: ManuscriptVersion,
    reviewer: User,
    scores: tuple[int, int, int, int],
    recommendation: ReviewRecommendation,
    comments_to_author: str,
    confidential_comments: str | None,
) -> Review:
    existing = db.scalar(
        select(Review).where(Review.invitation_id == invitation.id)
    )
    if existing is not None:
        return existing

    review = Review(
        invitation_id=invitation.id,
        manuscript_id=manuscript.id,
        manuscript_version_id=version.id,
        reviewer_id=reviewer.id,
        review_round=invitation.review_round,
        originality_score=scores[0],
        methodology_score=scores[1],
        clarity_score=scores[2],
        significance_score=scores[3],
        recommendation=recommendation.value,
        comments_to_author=comments_to_author,
        confidential_comments_to_editor=confidential_comments,
    )
    db.add(review)
    db.flush()
    return review


def _ensure_decision(
    db: Session,
    *,
    manuscript: Manuscript,
    review_round: int,
    decided_by: User,
    decision: EditorialDecisionType,
    decision_letter: str,
    override_reason: str | None = None,
) -> EditorialDecision:
    existing = db.scalar(
        select(EditorialDecision).where(
            EditorialDecision.manuscript_id == manuscript.id,
            EditorialDecision.review_round == review_round,
        )
    )
    if existing is not None:
        return existing

    record = EditorialDecision(
        manuscript_id=manuscript.id,
        review_round=review_round,
        manuscript_version_number=manuscript.current_version_number,
        decided_by_id=decided_by.id,
        decision=decision.value,
        decision_letter=decision_letter,
        override_reason=override_reason,
    )
    db.add(record)
    db.flush()
    return record


def seed_demo_data(db: Session, storage: StorageAdapter) -> SeedSummary:
    """Populate realistic, idempotent demo data across all Week 1 domain tables."""
    now = datetime.now(UTC)

    # 1. Users
    admin = _get_or_create_user(
        db,
        email="admin@journal-platform.org",
        full_name="Dr. Elena Vance",
        affiliation="Scholarly Platform Operations",
        is_system_admin=True,
    )
    chief_cs = _get_or_create_user(
        db,
        email="chief.cs@journal-platform.org",
        full_name="Prof. Marcus Sterling",
        affiliation="Department of Computer Science, Northbridge University",
        orcid="0000-0002-1825-0097",
        expertise_keywords=["distributed systems", "software architecture", "formal verification"],
    )
    chief_bio = _get_or_create_user(
        db,
        email="chief.bio@journal-platform.org",
        full_name="Prof. Claire Moreau",
        affiliation="Institute for Open Biomedical Research",
        orcid="0000-0001-5109-3700",
        expertise_keywords=["bioinformatics", "clinical data", "open science"],
    )
    editor_cs = _get_or_create_user(
        db,
        email="editor.cs@journal-platform.org",
        full_name="Dr. David Chen",
        affiliation="School of Computing, Pacific Tech",
        expertise_keywords=["systems engineering", "databases", "cloud computing"],
    )
    editor_bio = _get_or_create_user(
        db,
        email="editor.bio@journal-platform.org",
        full_name="Dr. Sofia Alvarez",
        affiliation="Center for Genomic Informatics",
        expertise_keywords=["genomics", "biostatistics", "reproducibility"],
    )
    reviewer_1 = _get_or_create_user(
        db,
        email="reviewer1@uni-alpha.edu",
        full_name="Prof. Liam O'Connor",
        affiliation="University of Alpha",
        expertise_keywords=["distributed systems", "consensus", "fault tolerance"],
    )
    reviewer_2 = _get_or_create_user(
        db,
        email="reviewer2@uni-beta.edu",
        full_name="Dr. Priya Patel",
        affiliation="Beta Institute of Technology",
        expertise_keywords=["machine learning", "nlp", "automated peer review"],
    )
    reviewer_3 = _get_or_create_user(
        db,
        email="reviewer3@uni-gamma.edu",
        full_name="Dr. Henrik Lindholm",
        affiliation="Gamma Medical Center",
        expertise_keywords=["bioinformatics", "genomics", "open data"],
    )
    author_1 = _get_or_create_user(
        db,
        email="author1@uni-delta.edu",
        full_name="Dr. Hannah Brooks",
        affiliation="Delta State University",
        orcid="0000-0002-1694-233X",
        expertise_keywords=["consensus protocols", "edge computing"],
    )
    author_2 = _get_or_create_user(
        db,
        email="author2@uni-epsilon.edu",
        full_name="Dr. Kenji Takahashi",
        affiliation="Epsilon Research Lab",
        expertise_keywords=["open biomedical datasets", "clinical pipelines"],
    )

    # 2. Journals & Workflow Configs
    jcs = _get_or_create_journal(
        db,
        slug="jcs-research",
        title="Journal of Computing Systems",
        issn="2765-4321",
        description="Double-anonymous peer-reviewed journal for systems, architecture, and ML.",
        scope_keywords=["distributed systems", "software engineering", "machine learning"],
        publisher_name="Academic Computing Press",
        doi_prefix="10.9999",
        anonymity_mode=AnonymityMode.DOUBLE_ANONYMOUS,
        min_reviewers=2,
        require_desk_review=True,
        apc_enabled=False,
    )
    bio = _get_or_create_journal(
        db,
        slug="open-bio-data",
        title="Open Biomedical Data Journal",
        issn="2891-1120",
        description="Open-review journal dedicated to reproducible biomedical datasets and pipelines.",
        scope_keywords=["bioinformatics", "genomics", "open data"],
        publisher_name="Open Science Consortium",
        doi_prefix="10.9998",
        anonymity_mode=AnonymityMode.OPEN,
        min_reviewers=1,
        require_desk_review=False,
        apc_enabled=True,
        apc_amount_cents=50000,
        apc_currency="USD",
    )

    # 3. Per-journal RBAC memberships
    memberships_spec = [
        (jcs, chief_cs, JournalRole.CHIEF_EDITOR),
        (jcs, editor_cs, JournalRole.HANDLING_EDITOR),
        (jcs, reviewer_1, JournalRole.REVIEWER),
        (jcs, reviewer_2, JournalRole.REVIEWER),
        (jcs, author_1, JournalRole.AUTHOR),
        (bio, chief_bio, JournalRole.CHIEF_EDITOR),
        (bio, editor_bio, JournalRole.HANDLING_EDITOR),
        (bio, reviewer_1, JournalRole.REVIEWER),
        (bio, reviewer_3, JournalRole.REVIEWER),
        (bio, author_2, JournalRole.AUTHOR),
    ]
    for journal, user, role in memberships_spec:
        _ensure_membership(db, journal=journal, user=user, role=role, assigned_by=admin)

    # 4. Sample Manuscripts across workflow stages
    # (a) Draft
    _get_or_create_manuscript(
        db,
        storage,
        journal=jcs,
        submitter=author_1,
        assigned_editor=None,
        title="Energy-Aware Scheduling for Heterogeneous Edge Clusters",
        abstract="We propose a lightweight scheduler reducing tail latency and energy use on edge nodes.",
        keywords=["edge computing", "scheduling", "energy efficiency"],
        subject_area="Distributed Systems",
        status=ManuscriptStatus.DRAFT,
        current_review_round=0,
        co_authors_data=[
            {
                "full_name": author_1.full_name,
                "email": author_1.email,
                "affiliation": author_1.affiliation,
                "orcid": author_1.orcid,
                "is_corresponding": True,
                "user_id": author_1.id,
            }
        ],
        transitions=[],
        pdf_filename="edge_scheduling_v1.pdf",
        extracted_text="Energy-Aware Scheduling for Heterogeneous Edge Clusters abstract and experiments.",
        now=now,
    )

    # (b) Submitted
    _get_or_create_manuscript(
        db,
        storage,
        journal=jcs,
        submitter=author_1,
        assigned_editor=None,
        title="Deterministic Replay for Multi-Tenant Serverless Workflows",
        abstract="A deterministic record-and-replay layer enabling reproducible debugging of serverless pipelines.",
        keywords=["serverless", "deterministic replay", "debugging"],
        subject_area="Cloud Systems",
        status=ManuscriptStatus.SUBMITTED,
        current_review_round=0,
        co_authors_data=[
            {
                "full_name": author_1.full_name,
                "email": author_1.email,
                "affiliation": author_1.affiliation,
                "orcid": author_1.orcid,
                "is_corresponding": True,
                "user_id": author_1.id,
            }
        ],
        transitions=[
            (ManuscriptStatus.DRAFT, ManuscriptStatus.SUBMITTED, author_1, "Initial submission."),
        ],
        pdf_filename="serverless_replay_v1.pdf",
        extracted_text="Deterministic Replay for Multi-Tenant Serverless Workflows evaluation.",
        now=now,
    )

    # (c) Under Review (Double-Anonymous, 1 completed review + 1 pending invitation)
    ms_under_review, ver_under_review = _get_or_create_manuscript(
        db,
        storage,
        journal=jcs,
        submitter=author_1,
        assigned_editor=editor_cs,
        title="Byzantine Fault-Tolerant Consensus Under Asymmetric Network Partitions",
        abstract="We analyze consensus safety and liveness under asymmetric partition models.",
        keywords=["consensus", "fault tolerance", "distributed systems"],
        subject_area="Distributed Systems",
        status=ManuscriptStatus.UNDER_REVIEW,
        current_review_round=1,
        co_authors_data=[
            {
                "full_name": author_1.full_name,
                "email": author_1.email,
                "affiliation": author_1.affiliation,
                "orcid": author_1.orcid,
                "is_corresponding": True,
                "user_id": author_1.id,
            },
            {
                "full_name": "Dr. Nora Lindqvist",
                "email": "nora.lindqvist@uni-delta.edu",
                "affiliation": "Delta State University",
                "is_corresponding": False,
            },
        ],
        transitions=[
            (ManuscriptStatus.DRAFT, ManuscriptStatus.SUBMITTED, author_1, "Initial submission."),
            (ManuscriptStatus.SUBMITTED, ManuscriptStatus.DESK_REVIEW, editor_cs, "Starting desk review."),
            (ManuscriptStatus.DESK_REVIEW, ManuscriptStatus.UNDER_REVIEW, editor_cs, "In scope; advancing to peer review."),
        ],
        pdf_filename="bft_consensus_v1.pdf",
        extracted_text="Byzantine Fault-Tolerant Consensus Under Asymmetric Network Partitions proofs and benchmarks.",
        now=now,
    )
    inv_ur_1 = _ensure_invitation(
        db,
        manuscript=ms_under_review,
        reviewer=reviewer_1,
        invited_by=editor_cs,
        review_round=1,
        status=ReviewInvitationStatus.COMPLETED,
        due_at=now + timedelta(days=14),
        responded_at=now - timedelta(days=5),
    )
    _ensure_review(
        db,
        invitation=inv_ur_1,
        manuscript=ms_under_review,
        version=ver_under_review,
        reviewer=reviewer_1,
        scores=(5, 4, 4, 5),
        recommendation=ReviewRecommendation.MINOR_REVISION,
        comments_to_author="Strong theoretical proofs; please clarify assumption A2 in Section 3.",
        confidential_comments="Confidential to editor: solid paper, recommend minor revision once second review arrives.",
    )
    _ensure_invitation(
        db,
        manuscript=ms_under_review,
        reviewer=reviewer_2,
        invited_by=editor_cs,
        review_round=1,
        status=ReviewInvitationStatus.PENDING,
        due_at=now + timedelta(days=18),
    )

    # (d) Revision Requested (2 completed reviews + major_revision EditorialDecision)
    ms_revision, ver_revision = _get_or_create_manuscript(
        db,
        storage,
        journal=jcs,
        submitter=author_1,
        assigned_editor=editor_cs,
        title="Adaptive Index Tuning for Hybrid Transactional-Analytical Workloads",
        abstract="We evaluate reinforcement-learning-assisted index selection under mixed HTAP workloads.",
        keywords=["databases", "index tuning", "machine learning"],
        subject_area="Data Systems",
        status=ManuscriptStatus.REVISION_REQUESTED,
        current_review_round=1,
        co_authors_data=[
            {
                "full_name": author_1.full_name,
                "email": author_1.email,
                "affiliation": author_1.affiliation,
                "orcid": author_1.orcid,
                "is_corresponding": True,
                "user_id": author_1.id,
            }
        ],
        transitions=[
            (ManuscriptStatus.DRAFT, ManuscriptStatus.SUBMITTED, author_1, "Initial submission."),
            (ManuscriptStatus.SUBMITTED, ManuscriptStatus.DESK_REVIEW, editor_cs, "Desk check started."),
            (ManuscriptStatus.DESK_REVIEW, ManuscriptStatus.UNDER_REVIEW, editor_cs, "Sent to external review."),
            (ManuscriptStatus.UNDER_REVIEW, ManuscriptStatus.REVISION_REQUESTED, editor_cs, "Editorial decision: major_revision"),
        ],
        pdf_filename="htap_indexing_v1.pdf",
        extracted_text="Adaptive Index Tuning for Hybrid Transactional-Analytical Workloads experimental results.",
        now=now,
    )
    inv_rev_1 = _ensure_invitation(
        db,
        manuscript=ms_revision,
        reviewer=reviewer_1,
        invited_by=editor_cs,
        review_round=1,
        status=ReviewInvitationStatus.COMPLETED,
        due_at=now + timedelta(days=10),
        responded_at=now - timedelta(days=7),
    )
    inv_rev_2 = _ensure_invitation(
        db,
        manuscript=ms_revision,
        reviewer=reviewer_2,
        invited_by=editor_cs,
        review_round=1,
        status=ReviewInvitationStatus.COMPLETED,
        due_at=now + timedelta(days=10),
        responded_at=now - timedelta(days=6),
    )
    _ensure_review(
        db,
        invitation=inv_rev_1,
        manuscript=ms_revision,
        version=ver_revision,
        reviewer=reviewer_1,
        scores=(4, 3, 4, 4),
        recommendation=ReviewRecommendation.MAJOR_REVISION,
        comments_to_author="Please compare against baseline heuristic tuners on TPC-CH.",
        confidential_comments="Needs stronger baseline comparison before acceptance.",
    )
    _ensure_review(
        db,
        invitation=inv_rev_2,
        manuscript=ms_revision,
        version=ver_revision,
        reviewer=reviewer_2,
        scores=(4, 4, 3, 4),
        recommendation=ReviewRecommendation.MINOR_REVISION,
        comments_to_author="Clarify reward function hyperparameters in Section 4.",
        confidential_comments="Promising work; happy to re-review v2.",
    )
    _ensure_decision(
        db,
        manuscript=ms_revision,
        review_round=1,
        decided_by=editor_cs,
        decision=EditorialDecisionType.MAJOR_REVISION,
        decision_letter="Both reviewers see strong potential. Please upload a revised PDF addressing the baseline comparison and hyperparameter clarity.",
    )

    # (e) Accepted (Open-review journal, 1 completed review + accept EditorialDecision)
    ms_accepted, ver_accepted = _get_or_create_manuscript(
        db,
        storage,
        journal=bio,
        submitter=author_2,
        assigned_editor=editor_bio,
        title="Curated Multi-Cohort Open Benchmark for Clinical Variant Annotation",
        abstract="An open, standardized dataset and validation suite for reproducible clinical variant interpretation.",
        keywords=["bioinformatics", "genomics", "open data"],
        subject_area="Biomedical Informatics",
        status=ManuscriptStatus.ACCEPTED,
        current_review_round=1,
        co_authors_data=[
            {
                "full_name": author_2.full_name,
                "email": author_2.email,
                "affiliation": author_2.affiliation,
                "is_corresponding": True,
                "user_id": author_2.id,
            }
        ],
        transitions=[
            (ManuscriptStatus.DRAFT, ManuscriptStatus.SUBMITTED, author_2, "Initial submission."),
            (ManuscriptStatus.SUBMITTED, ManuscriptStatus.UNDER_REVIEW, editor_bio, "Desk review disabled; advancing directly to peer review."),
            (ManuscriptStatus.UNDER_REVIEW, ManuscriptStatus.ACCEPTED, editor_bio, "Editorial decision: accept"),
        ],
        pdf_filename="clinical_variant_benchmark_v1.pdf",
        extracted_text="Curated Multi-Cohort Open Benchmark for Clinical Variant Annotation methodology and cohort metrics.",
        now=now,
    )
    inv_acc_1 = _ensure_invitation(
        db,
        manuscript=ms_accepted,
        reviewer=reviewer_3,
        invited_by=editor_bio,
        review_round=1,
        status=ReviewInvitationStatus.COMPLETED,
        due_at=now + timedelta(days=7),
        responded_at=now - timedelta(days=5),
    )
    _ensure_review(
        db,
        invitation=inv_acc_1,
        manuscript=ms_accepted,
        version=ver_accepted,
        reviewer=reviewer_3,
        scores=(5, 5, 5, 5),
        recommendation=ReviewRecommendation.ACCEPT,
        comments_to_author="Exemplary open-science dataset with complete documentation and reproducibility scripts.",
        confidential_comments="Confidential to editor: ready for immediate acceptance.",
    )
    _ensure_decision(
        db,
        manuscript=ms_accepted,
        review_round=1,
        decided_by=editor_bio,
        decision=EditorialDecisionType.ACCEPT,
        decision_letter="Congratulations! Your manuscript has been accepted for publication in Open Biomedical Data Journal.",
    )

    db.commit()

    return SeedSummary(
        users=db.query(User).count(),
        journals=db.query(Journal).count(),
        memberships=db.query(JournalMembership).count(),
        manuscripts=db.query(Manuscript).count(),
        versions=db.query(ManuscriptVersion).count(),
        invitations=db.query(ReviewInvitation).count(),
        reviews=db.query(Review).count(),
        decisions=db.query(EditorialDecision).count(),
    )


def main() -> None:
    """Run demo seed against the configured DATABASE_URL and STORAGE_DIR."""
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    storage = LocalFilesystemStorageAdapter(Path(settings.storage_dir))

    with session_factory() as db:
        summary = seed_demo_data(db, storage)

    engine.dispose()
    print("Demo seed completed (idempotent):")
    print(f"  Users:        {summary.users}")
    print(f"  Journals:     {summary.journals}")
    print(f"  Memberships:  {summary.memberships}")
    print(f"  Manuscripts:  {summary.manuscripts}")
    print(f"  Versions:     {summary.versions}")
    print(f"  Invitations:  {summary.invitations}")
    print(f"  Reviews:      {summary.reviews}")
    print(f"  Decisions:    {summary.decisions}")
    print(f"  Demo password for all seeded accounts: {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()

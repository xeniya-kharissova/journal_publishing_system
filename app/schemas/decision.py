"""Pydantic schemas for formal editorial decisions."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.decision import EditorialDecisionType


class EditorialDecisionCreateRequest(BaseModel):
    """Payload for recording a formal editorial decision on a manuscript under review."""

    decision: EditorialDecisionType
    decision_letter: str = Field(..., min_length=1, max_length=20000)
    override_reason: str | None = Field(
        default=None,
        max_length=4000,
        description="Chief Editor / System Admin justification when overriding accept quality gates.",
    )

    @field_validator("decision_letter")
    @classmethod
    def _validate_decision_letter(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("decision_letter cannot be blank.")
        return stripped

    @field_validator("override_reason")
    @classmethod
    def _clean_override_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class EditorialDecisionResponse(BaseModel):
    """Recorded formal editorial decision for a specific review round."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    manuscript_id: int
    review_round: int
    manuscript_version_number: int
    decided_by_id: int | None
    decision: EditorialDecisionType
    decision_letter: str
    override_reason: str | None
    created_at: datetime

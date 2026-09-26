"""
Pydantic v2 schemas for deterministic curriculum evaluation and quality gating.
Enforces rigorous pedagogical, technical, and structural criteria.
"""
from __future__ import annotations

from enum import Enum
from typing import List
from pydantic import BaseModel, Field, field_validator


class GatingDecision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class EvaluationCriterion(BaseModel):
    """Specific scoring dimension evaluated by the Judge."""
    criterion_id: str = Field(description="Unique identifier e.g., 'pedagogical_depth', 'code_correctness'")
    name: str = Field(description="Human-readable title of the criterion")
    score: float = Field(ge=0.0, le=100.0, description="Score on a 0-100 normalized scale")
    weight: float = Field(ge=0.0, le=1.0, description="Importance weight of this criterion in [0, 1]")
    reasoning: str = Field(description="Detailed rationale justifying the assigned score")
    suggestions: List[str] = Field(default_factory=list, description="Targeted improvements for this dimension")


class EvaluationReport(BaseModel):
    """
    Deterministic evaluation report produced by the Judge Agent.
    Strictly validated against enterprise educational thresholds.
    """
    overall_score: float = Field(
        ge=0.0,
        le=100.0,
        description="Weighted aggregate score across all evaluation dimensions",
    )
    decision: GatingDecision = Field(
        description="Pass/Fail gating decision based on threshold and critical failures"
    )
    passed: bool = Field(
        description="Boolean flag indicating whether the content passes quality gating"
    )
    strengths: List[str] = Field(
        description="Key technical and pedagogical strengths identified in the material"
    )
    weaknesses: List[str] = Field(
        description="Deficiencies or omissions requiring remediation"
    )
    actionable_revisions: List[str] = Field(
        description="Explicit, numbered steps the ContentBuilder must execute to reach passing standards"
    )
    criteria_breakdown: List[EvaluationCriterion] = Field(
        description="Itemized scorecards across technical, architectural, and educational facets"
    )

    @field_validator("passed", mode="after")
    @classmethod
    def reconcile_passed_status(cls, v: bool, info) -> bool:
        """Enforces consistency between decision enum and passed boolean."""
        decision = info.data.get("decision")
        if decision == GatingDecision.PASS:
            return True
        elif decision == GatingDecision.FAIL:
            return False
        return v

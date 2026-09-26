"""
Judge Agent.
Deterministic evaluation agent operating over Gemini 2.5 Pro with structured Pydantic v2 schemas.
Acts as a strict pedagogical and technical quality gate before publishing.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional
from google import genai
from google.genai import types
from .schemas import EvaluationReport, GatingDecision

logger = logging.getLogger("agent.judge")


class JudgeAgent:
    """
    Judge Agent executing deterministic rubric-based audits on generated curriculum.
    Enforces pass/fail gating threshold (default 85/100).
    """

    DEFAULT_THRESHOLD = 85.0

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: Optional[str] = None,
        model_name: Optional[str] = None,
        pass_threshold: Optional[float] = None,
    ):
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        self.model_name = model_name or os.getenv("GEMINI_JUDGE_MODEL", "gemini-2.5-pro")
        # An explicit argument outranks the environment; the env var is only the default.
        self.pass_threshold = (
            float(pass_threshold)
            if pass_threshold is not None
            else float(os.getenv("PASSING_SCORE_THRESHOLD", self.DEFAULT_THRESHOLD))
        )

        if self.project_id:
            self.client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=self.location,
            )
            logger.info("JudgeAgent initialized via Vertex AI [Project: %s, Threshold: %.1f]", self.project_id, self.pass_threshold)
        else:
            self.client = genai.Client()
            logger.info("JudgeAgent initialized via Google GenAI Client [Threshold: %.1f]", self.pass_threshold)

    def _build_system_instruction(self) -> str:
        return (
            "You are a Senior Principal AI Curriculum Evaluator and Technical Auditor. "
            "Your role is to rigorously inspect educational modules for: "
            "1. Architectural accuracy and factual correctness. "
            "2. Executability, security, and realistic idioms in all code snippets. "
            "3. Clear pedagogical progression (scaffolding, Bloom's taxonomy). "
            "4. Inclusion of production failure modes and diagnostic deep-dives. "
            "5. Proper markdown syntax, callouts, and self-assessment checkpoints. "
            "Be uncompromising. If a module lacks depth or contains hand-waving explanations, "
            f"assign a failing score (< {self.pass_threshold}) with concrete, actionable revisions."
        )

    async def evaluate(
        self,
        topic: str,
        content: str,
        research_context: Optional[dict] = None,
        iteration: int = 1,
    ) -> EvaluationReport:
        """
        Audits course content against a 5-dimension enterprise evaluation rubric.
        Returns a strongly typed EvaluationReport.
        """
        logger.info("Executing Judge evaluation (Iteration %d) on topic: '%s'", iteration, topic)

        context_snippet = json.dumps(research_context, indent=2) if research_context else "No prior research provided."

        prompt = f"""
Evaluate the following generated course content for topic: "{topic}" (Iteration {iteration}).

Evaluation Rubric Dimensions:
1. "technical_depth" (Weight 0.25): Are complex distributed systems / engineering mechanics explained with depth, or is it superficial?
2. "code_correctness" (Weight 0.25): Are code snippets idiomatic, complete, syntactically correct, and free of security risks?
3. "pedagogical_flow" (Weight 0.20): Does the lesson build logically from foundations to edge-case handling?
4. "production_realism" (Weight 0.15): Are real-world failure modes, latency bottlenecks, or operational trade-offs addressed?
5. "structural_formatting" (Weight 0.15): Are headings well-organized, code languages specified, and callouts (> [!NOTE], etc.) properly used?

Research Grounding Reference:
{context_snippet[:1500]}

Generated Course Content to Audit:
----------------------------------------
{content}
----------------------------------------

Grading Threshold:
- Overall Passing Threshold: {self.pass_threshold} / 100.
- If overall_score >= {self.pass_threshold}, decision MUST be "PASS", passed = true.
- If overall_score < {self.pass_threshold}, decision MUST be "FAIL", passed = false.
- You MUST provide specific, numbered actionable_revisions explaining exactly what code or sections need rewriting if failing.

Emit your audit exclusively as a JSON object adhering to the schema:
{{
  "overall_score": 88.5,
  "decision": "PASS",
  "passed": true,
  "strengths": ["Item 1", "Item 2"],
  "weaknesses": ["Item 1"],
  "actionable_revisions": ["Revision 1 if failed, or polishing items if passed"],
  "criteria_breakdown": [
    {{
      "criterion_id": "technical_depth",
      "name": "Technical Depth & Invariant Rigor",
      "score": 90.0,
      "weight": 0.25,
      "reasoning": "Thorough discussion of consensus invariants.",
      "suggestions": ["Include memory allocation metrics"]
    }}
  ]
}}
"""

        # In Gemini 2.5, we can use structured outputs via response_schema and response_mime_type
        config = types.GenerateContentConfig(
            system_instruction=self._build_system_instruction(),
            response_mime_type="application/json",
            response_schema=EvaluationReport,
            temperature=0.1,
            max_output_tokens=4096,
        )

        # No heuristic fallback: an API or schema failure must surface as a failure.
        # Substituting an invented score would let un-evaluated content clear the gate.
        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config,
        )

        raw_text = response.text or ""
        if not raw_text.strip():
            raise RuntimeError(
                "Judge model returned an empty response (possible safety block or token limit)."
            )

        report = EvaluationReport.model_validate_json(raw_text)

        # The threshold, not the model's self-reported verdict, decides the gate.
        report.passed = report.overall_score >= self.pass_threshold
        report.decision = GatingDecision.PASS if report.passed else GatingDecision.FAIL

        logger.info(
            "Judge evaluation complete: Score=%.1f/100, Decision=%s",
            report.overall_score,
            report.decision.value,
        )
        return report

"""
Orchestrator Agent.
Implements:
1. LoopAgent: Iterative critique and refinement loop between ContentBuilder and Judge.
2. SequentialAgent: Multi-stage pipeline coordinating Ingestion -> Research -> Loop -> Packaging.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import List, Optional
from pydantic import BaseModel, Field

from agents.researcher.agent import ResearcherAgent, ResearchReport
from agents.content_builder.agent import ContentBuilderAgent
from agents.judge.agent import JudgeAgent
from agents.judge.schemas import EvaluationReport, GatingDecision

logger = logging.getLogger("agent.orchestrator")


class IterationSnapshot(BaseModel):
    """Telemetry captured for each iteration in the LoopAgent."""
    iteration: int
    score: float
    decision: str
    duration_seconds: float
    actionable_revisions: List[str]
    word_count: int


class PipelineTelemetry(BaseModel):
    """Execution metrics and audit trail for the sequential pipeline."""
    total_duration_seconds: float
    research_duration_seconds: float
    loop_duration_seconds: float
    iterations_executed: int
    converged: bool
    final_score: float
    snapshots: List[IterationSnapshot] = Field(default_factory=list)


class PipelineResult(BaseModel):
    """Final package produced by the multi-agent course creation engine."""
    topic: str
    audience: str
    final_markdown: str
    research_report: ResearchReport
    final_evaluation: EvaluationReport
    telemetry: PipelineTelemetry


class LoopAgent:
    """
    LoopAgent executes an iterative critique loop between a ContentBuilder and a Judge.
    Continues until the Judge returns a PASS (score >= threshold) or max_iterations is reached.
    """

    def __init__(
        self,
        builder: ContentBuilderAgent,
        judge: JudgeAgent,
        max_iterations: int = 3,
    ):
        self.builder = builder
        self.judge = judge
        self.max_iterations = max_iterations

    async def execute(
        self,
        topic: str,
        research_context: dict,
    ) -> tuple[str, EvaluationReport, List[IterationSnapshot]]:
        """
        Executes the optimization loop:
        ContentBuilder -> FormatValidator -> Judge -> (Evaluate) -> Loop/Exit.
        """
        current_content = ""
        current_revisions: Optional[List[str]] = None
        snapshots: List[IterationSnapshot] = []
        final_evaluation: Optional[EvaluationReport] = None

        for iteration in range(1, self.max_iterations + 1):
            iter_start = time.perf_counter()
            logger.info("=== LoopAgent Iteration %d / %d ===", iteration, self.max_iterations)

            # Step 1: Synthesize / Refine Content
            current_content = await self.builder.build(
                topic=topic,
                research_context=research_context,
                critique_revisions=current_revisions,
                iteration=iteration,
            )

            # Step 2: Audit Content via Judge Agent
            final_evaluation = await self.judge.evaluate(
                topic=topic,
                content=current_content,
                research_context=research_context,
                iteration=iteration,
            )

            iter_duration = time.perf_counter() - iter_start
            snapshot = IterationSnapshot(
                iteration=iteration,
                score=final_evaluation.overall_score,
                decision=final_evaluation.decision.value,
                duration_seconds=round(iter_duration, 2),
                actionable_revisions=final_evaluation.actionable_revisions,
                word_count=len(current_content.split()),
            )
            snapshots.append(snapshot)

            logger.info(
                "Iteration %d Completed in %.2fs | Score: %.1f | Decision: %s",
                iteration,
                iter_duration,
                final_evaluation.overall_score,
                final_evaluation.decision.value,
            )

            # Gating check: if passed, terminate loop early
            if final_evaluation.passed:
                logger.info("Content passed quality gating on iteration %d! Exiting loop.", iteration)
                break
            else:
                logger.warning(
                    "Content failed quality gating (Score: %.1f < %.1f). Feeding revisions into next cycle.",
                    final_evaluation.overall_score,
                    self.judge.pass_threshold,
                )
                current_revisions = final_evaluation.actionable_revisions

        return current_content, final_evaluation, snapshots


class SequentialAgent:
    """
    SequentialAgent coordinates the macro pipeline stages in an end-to-end directed acyclic graph:
    [Topic Ingestion] -> [ResearcherAgent (Grounded Search)] -> [LoopAgent (Builder <-> Judge)] -> [Packaging]
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: Optional[str] = None,
        max_iterations: Optional[int] = None,
        pass_threshold: Optional[float] = None,
    ):
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        max_iter = max_iterations or int(os.getenv("MAX_CRITIQUE_ITERATIONS", 3))
        threshold = pass_threshold or float(os.getenv("PASSING_SCORE_THRESHOLD", 85.0))

        # Instantiate specialized agents
        self.researcher = ResearcherAgent(project_id=self.project_id, location=self.location)
        self.builder = ContentBuilderAgent(project_id=self.project_id, location=self.location)
        self.judge = JudgeAgent(project_id=self.project_id, location=self.location, pass_threshold=threshold)
        self.loop_agent = LoopAgent(builder=self.builder, judge=self.judge, max_iterations=max_iter)

    async def run(
        self,
        topic: str,
        audience: str = "Senior Software Engineers",
        focus_areas: Optional[List[str]] = None,
    ) -> PipelineResult:
        """Runs the complete sequential multi-agent course creation pipeline."""
        start_time = time.perf_counter()
        logger.info("Initializing Sequential Course Engine for topic: '%s'", topic)

        # Stage 1: Grounded Deep Research
        t0 = time.perf_counter()
        research_report = await self.researcher.research(
            topic=topic,
            audience=audience,
            focus_areas=focus_areas,
        )
        research_duration = time.perf_counter() - t0
        logger.info("Stage 1 (Research) completed in %.2fs", research_duration)

        # Stage 2: Evaluator-Optimizer Loop
        t1 = time.perf_counter()
        final_markdown, final_eval, snapshots = await self.loop_agent.execute(
            topic=topic,
            research_context=research_report.model_dump(),
        )
        loop_duration = time.perf_counter() - t1
        logger.info("Stage 2 (Loop Optimization) completed in %.2fs", loop_duration)

        # Stage 3: Packaging & Telemetry Compilation
        total_duration = time.perf_counter() - start_time
        telemetry = PipelineTelemetry(
            total_duration_seconds=round(total_duration, 2),
            research_duration_seconds=round(research_duration, 2),
            loop_duration_seconds=round(loop_duration, 2),
            iterations_executed=len(snapshots),
            converged=final_eval.passed,
            final_score=final_eval.overall_score,
            snapshots=snapshots,
        )

        logger.info(
            "Sequential Pipeline Finished! Final Score: %.1f/100 | Converged: %s | Total Time: %.2fs",
            telemetry.final_score,
            telemetry.converged,
            telemetry.total_duration_seconds,
        )

        return PipelineResult(
            topic=topic,
            audience=audience,
            final_markdown=final_markdown,
            research_report=research_report,
            final_evaluation=final_eval,
            telemetry=telemetry,
        )

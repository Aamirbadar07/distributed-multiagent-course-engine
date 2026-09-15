"""
Agent-to-Agent (A2A) HTTP Protocol Server.
Exposes standard RESTful microservice contracts for orchestrating agents
in distributed Google Cloud Run and Kubernetes architectures.
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agents.orchestrator.orchestrator import SequentialAgent, PipelineResult
from agents.researcher.agent import ResearcherAgent, ResearchReport
from agents.content_builder.agent import ContentBuilderAgent
from agents.judge.agent import JudgeAgent
from agents.judge.schemas import EvaluationReport

# Configure structured application logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("a2a.server")

app = FastAPI(
    title="Distributed Multi-Agent Course Creation Engine",
    version="1.0.0",
    description="Production A2A HTTP Server coordinating Google GenAI / Gemini 2.5 Multi-Agent Swarms.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global engine instances initialized on startup
engine: Optional[SequentialAgent] = None


@app.on_event("startup")
async def startup_event():
    global engine
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    logger.info("Starting A2A Server with Project=%s, Location=%s", project_id, location)
    engine = SequentialAgent(project_id=project_id, location=location)


# --- Request / Response Schemas ---
class GenerateCourseRequest(BaseModel):
    topic: str = Field(..., example="Advanced Distributed Systems with Rust and Raft")
    audience: str = Field(default="Senior Software Engineers", example="Senior Staff Engineers")
    focus_areas: Optional[List[str]] = Field(default=None, example=["Leader Election", "Log Compaction", "Network Partitions"])


class ResearchRequest(BaseModel):
    topic: str
    audience: str = "Senior Software Engineers"
    focus_areas: Optional[List[str]] = None


class BuilderRequest(BaseModel):
    topic: str
    research_context: Optional[dict] = None
    critique_revisions: Optional[List[str]] = None
    iteration: int = 1


class JudgeRequest(BaseModel):
    topic: str
    content: str
    research_context: Optional[dict] = None
    iteration: int = 1


# --- Endpoints ---
@app.get("/healthz", status_code=status.HTTP_200_OK)
async def healthz():
    """Liveness and readiness probe for Google Cloud Run."""
    return {"status": "healthy", "service": "distributed-multiagent-course-engine"}


@app.post("/v1/orchestrator/generate", response_model=PipelineResult)
async def orchestrate_course_generation(req: GenerateCourseRequest):
    """
    End-to-End Orchestrator Pipeline.
    Executes grounded research followed by iterative critique-refinement loops.
    """
    if not engine:
        raise HTTPException(status_code=500, detail="SequentialAgent engine not initialized")
    try:
        result = await engine.run(
            topic=req.topic,
            audience=req.audience,
            focus_areas=req.focus_areas,
        )
        return result
    except Exception as exc:
        logger.exception("Pipeline orchestration failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/v1/agents/researcher", response_model=ResearchReport)
async def invoke_researcher_agent(req: ResearchRequest):
    """Dedicated A2A HTTP endpoint for the Researcher Agent."""
    researcher = ResearcherAgent()
    try:
        report = await researcher.research(
            topic=req.topic,
            audience=req.audience,
            focus_areas=req.focus_areas,
        )
        return report
    except Exception as exc:
        logger.exception("Researcher agent error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/v1/agents/builder")
async def invoke_builder_agent(req: BuilderRequest):
    """Dedicated A2A HTTP endpoint for the Content Builder Agent."""
    builder = ContentBuilderAgent()
    try:
        markdown = await builder.build(
            topic=req.topic,
            research_context=req.research_context,
            critique_revisions=req.critique_revisions,
            iteration=req.iteration,
        )
        return {"content": markdown}
    except Exception as exc:
        logger.exception("Builder agent error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/v1/agents/judge", response_model=EvaluationReport)
async def invoke_judge_agent(req: JudgeRequest):
    """Dedicated A2A HTTP endpoint for the Judge Agent."""
    judge = JudgeAgent()
    try:
        eval_report = await judge.evaluate(
            topic=req.topic,
            content=req.content,
            research_context=req.research_context,
            iteration=req.iteration,
        )
        return eval_report
    except Exception as exc:
        logger.exception("Judge agent error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("agents.orchestrator.a2a_server:app", host="0.0.0.0", port=port, reload=False)

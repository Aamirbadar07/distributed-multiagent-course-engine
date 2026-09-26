"""
Agent-to-Agent (A2A) HTTP Protocol Server.
Exposes standard RESTful microservice contracts for orchestrating agents
in distributed Google Cloud Run and Kubernetes architectures.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agents.orchestrator.orchestrator import SequentialAgent, PipelineResult
from agents.researcher.agent import ResearchReport
from agents.judge.schemas import EvaluationReport

# Loaded here so the .env workflow documented in the README actually takes effect.
load_dotenv()

# Configure structured application logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("a2a.server")

# Single engine instance shared by every request; it owns one GenAI client per agent.
engine: Optional[SequentialAgent] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    logger.info("Starting A2A Server with Project=%s, Location=%s", project_id, location)
    engine = SequentialAgent(project_id=project_id, location=location)
    yield
    engine = None


app = FastAPI(
    title="Distributed Multi-Agent Course Creation Engine",
    version="1.0.0",
    description="Production A2A HTTP Server coordinating Google GenAI / Gemini 2.5 Multi-Agent Swarms.",
    lifespan=lifespan,
)

# CORS is off unless an explicit allowlist is configured. A wildcard origin combined
# with credentials is rejected by browsers and unsafe the moment auth is introduced.
cors_origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )
    logger.info("CORS enabled for origins: %s", cors_origins)


def _require_engine() -> SequentialAgent:
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine is not initialized.")
    return engine


# --- Request / Response Schemas ---
class GenerateCourseRequest(BaseModel):
    topic: str = Field(..., examples=["Advanced Distributed Systems with Rust and Raft"])
    audience: str = Field(default="Senior Software Engineers", examples=["Senior Staff Engineers"])
    focus_areas: Optional[List[str]] = Field(
        default=None,
        examples=[["Leader Election", "Log Compaction", "Network Partitions"]],
    )


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
# Failures return a generic message; the detail stays in the server log so that
# project ids, service accounts and internal paths are never echoed to callers.
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
    eng = _require_engine()
    try:
        return await eng.run(
            topic=req.topic,
            audience=req.audience,
            focus_areas=req.focus_areas,
        )
    except Exception:
        logger.exception("Pipeline orchestration failed")
        raise HTTPException(status_code=500, detail="Pipeline orchestration failed.")


@app.post("/v1/agents/researcher", response_model=ResearchReport)
async def invoke_researcher_agent(req: ResearchRequest):
    """Dedicated A2A HTTP endpoint for the Researcher Agent."""
    eng = _require_engine()
    try:
        return await eng.researcher.research(
            topic=req.topic,
            audience=req.audience,
            focus_areas=req.focus_areas,
        )
    except Exception:
        logger.exception("Researcher agent failed")
        raise HTTPException(status_code=500, detail="Researcher agent failed.")


@app.post("/v1/agents/builder")
async def invoke_builder_agent(req: BuilderRequest):
    """Dedicated A2A HTTP endpoint for the Content Builder Agent."""
    eng = _require_engine()
    try:
        markdown = await eng.builder.build(
            topic=req.topic,
            research_context=req.research_context,
            critique_revisions=req.critique_revisions,
            iteration=req.iteration,
        )
    except Exception:
        logger.exception("Builder agent failed")
        raise HTTPException(status_code=500, detail="Builder agent failed.")

    validation = eng.loop_agent.validator.validate(markdown)
    return {"content": markdown, "validation": validation.model_dump()}


@app.post("/v1/agents/judge", response_model=EvaluationReport)
async def invoke_judge_agent(req: JudgeRequest):
    """Dedicated A2A HTTP endpoint for the Judge Agent."""
    eng = _require_engine()
    try:
        return await eng.judge.evaluate(
            topic=req.topic,
            content=req.content,
            research_context=req.research_context,
            iteration=req.iteration,
        )
    except Exception:
        logger.exception("Judge agent failed")
        raise HTTPException(status_code=500, detail="Judge agent failed.")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("agents.orchestrator.a2a_server:app", host="0.0.0.0", port=port, reload=False)

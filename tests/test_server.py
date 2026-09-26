"""
Smoke tests for the A2A HTTP surface: startup wiring, the health probe,
CORS defaults, and that handler failures do not leak internals to callers.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agents.judge import agent as judge_module
from agents.orchestrator import a2a_server


@pytest.fixture
def client(monkeypatch):
    """Boots the app with the GenAI client stubbed out, so no credentials are needed."""
    monkeypatch.setattr(judge_module.genai, "Client", lambda **kwargs: object())
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    with TestClient(a2a_server.app) as test_client:
        yield test_client


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_engine_is_shared_across_requests(client):
    """Agents are constructed once at startup, not per request."""
    engine = a2a_server.engine
    assert engine is not None
    assert engine.loop_agent.builder is engine.builder
    assert engine.loop_agent.judge is engine.judge


def test_no_cors_headers_by_default(client):
    response = client.get("/healthz", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_agent_failure_returns_generic_detail(client, monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("project=secret-123 service-account=sa@internal")

    monkeypatch.setattr(a2a_server.engine.judge, "evaluate", boom)

    response = client.post(
        "/v1/agents/judge",
        json={"topic": "raft", "content": "# Course"},
    )

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail == "Judge agent failed."
    assert "secret-123" not in detail


def test_builder_endpoint_reports_validation(client, monkeypatch):
    async def build(**kwargs):
        return "# Tiny\n\nnot nearly long enough"

    monkeypatch.setattr(a2a_server.engine.builder, "build", build)

    response = client.post("/v1/agents/builder", json={"topic": "raft"})

    assert response.status_code == 200
    body = response.json()
    assert body["content"].startswith("# Tiny")
    assert body["validation"]["is_valid"] is False
    assert body["validation"]["errors"]

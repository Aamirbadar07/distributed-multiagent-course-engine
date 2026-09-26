"""
Tests for the deterministic, non-network parts of the engine: the markdown format
validator, the gating schemas, threshold resolution, and the LoopAgent's two gates.
Model calls are replaced with stubs, so no credentials or network access are needed.
"""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from agents.content_builder.format_validator import MarkdownFormatValidator
from agents.judge import agent as judge_module
from agents.judge.agent import JudgeAgent
from agents.judge.schemas import EvaluationCriterion, EvaluationReport, GatingDecision
from agents.orchestrator.orchestrator import LoopAgent, SequentialAgent
from agents.researcher.agent import ModuleOutline, ResearchReport, ResearcherAgent

BODY = "consensus replication invariant " * 200

VALID_DOC = f"""# Raft Consensus

{BODY}

## Log Replication

{BODY}

```python
print("append_entries")
```

## Knowledge Check & Hands-on Lab

> [!NOTE]
> Leader completeness holds across terms.
"""

# Long enough to clear the word minimum, but no fenced code block at all.
NO_CODE_DOC = f"""# Raft Consensus

{BODY}

## Log Replication

{BODY}
"""


def _report(score: float, revisions: list[str] | None = None) -> EvaluationReport:
    passed = score >= 85.0
    return EvaluationReport(
        overall_score=score,
        decision=GatingDecision.PASS if passed else GatingDecision.FAIL,
        passed=passed,
        strengths=["clear scaffolding"],
        weaknesses=["thin on failure modes"],
        actionable_revisions=revisions if revisions is not None else ["judge revision"],
        criteria_breakdown=[
            EvaluationCriterion(
                criterion_id="technical_depth",
                name="Technical Depth",
                score=score,
                weight=1.0,
                reasoning="stub",
            )
        ],
    )


class StubBuilder:
    """Returns canned markdown and records the revisions it was asked to address."""

    def __init__(self, outputs: list[str]):
        self.outputs = outputs
        self.received_revisions: list[list[str] | None] = []

    async def build(self, topic, research_context=None, critique_revisions=None, iteration=1):
        self.received_revisions.append(critique_revisions)
        return self.outputs[min(iteration - 1, len(self.outputs) - 1)]


class StubJudge:
    def __init__(self, score: float, pass_threshold: float = 85.0):
        self.score = score
        self.pass_threshold = pass_threshold
        self.calls = 0

    async def evaluate(self, topic, content, research_context=None, iteration=1):
        self.calls += 1
        return _report(self.score)


class StubResearcher:
    async def research(self, topic, audience="Senior Software Engineers", focus_areas=None):
        return ResearchReport(
            topic=topic,
            executive_summary="stub summary",
            prerequisites=["python"],
            core_modules=[
                ModuleOutline(
                    module_number=1,
                    title="Foundations",
                    objectives=["understand quorums"],
                    key_concepts=["term", "quorum"],
                    hands_on_lab="Build a single-node log.",
                )
            ],
            common_pitfalls=["split brain"],
            sources=[],
        )


# --- Format validator ---------------------------------------------------------
def test_valid_document_passes():
    result = MarkdownFormatValidator().validate(VALID_DOC)
    assert result.is_valid, result.errors
    assert result.metrics["code_blocks"] == 1
    assert result.metrics["callouts_detected"] == 1


def test_empty_payload_is_invalid():
    result = MarkdownFormatValidator().validate("   ")
    assert not result.is_valid
    assert "empty" in result.errors[0].lower()


def test_code_block_without_language_is_an_error():
    doc = VALID_DOC.replace("```python", "```")
    result = MarkdownFormatValidator().validate(doc)
    assert not result.is_valid
    assert any("language specifier" in e for e in result.errors)


def test_skipped_heading_level_is_an_error():
    doc = VALID_DOC.replace("## Log Replication", "#### Log Replication")
    result = MarkdownFormatValidator().validate(doc)
    assert not result.is_valid
    assert any("Skipped heading level" in e for e in result.errors)


def test_unclosed_code_fence_is_an_error():
    result = MarkdownFormatValidator().validate(VALID_DOC + "\n```rust\nfn main() {}\n")
    assert not result.is_valid
    assert any("Unclosed code block" in e for e in result.errors)


def test_word_count_floor_is_enforced():
    result = MarkdownFormatValidator().validate("# Title\n\n```python\nx = 1\n```\n")
    assert not result.is_valid
    assert any("Word count" in e for e in result.errors)


def test_missing_code_block_is_an_error():
    result = MarkdownFormatValidator().validate(NO_CODE_DOC)
    assert not result.is_valid
    assert any("valid code blocks" in e for e in result.errors)


# --- Gating schema ------------------------------------------------------------
def test_fail_decision_forces_passed_false():
    report = _report(50.0)
    assert report.decision is GatingDecision.FAIL
    assert report.passed is False


def test_decision_overrides_inconsistent_passed_flag():
    report = EvaluationReport(
        overall_score=40.0,
        decision=GatingDecision.FAIL,
        passed=True,  # model contradicted itself; the validator reconciles it
        strengths=[],
        weaknesses=[],
        actionable_revisions=[],
        criteria_breakdown=[],
    )
    assert report.passed is False


# --- Threshold resolution ----------------------------------------------------
@pytest.fixture
def no_genai_client(monkeypatch):
    """Stops agent constructors from building a real GenAI client."""
    monkeypatch.setattr(judge_module.genai, "Client", lambda **kwargs: object())


def test_explicit_threshold_outranks_environment(no_genai_client, monkeypatch):
    monkeypatch.setenv("PASSING_SCORE_THRESHOLD", "85.0")
    judge = JudgeAgent(project_id="p", pass_threshold=95.0)
    assert judge.pass_threshold == 95.0


def test_environment_threshold_used_when_no_argument(no_genai_client, monkeypatch):
    monkeypatch.setenv("PASSING_SCORE_THRESHOLD", "70.5")
    assert JudgeAgent(project_id="p").pass_threshold == 70.5


def test_default_threshold_when_unset(no_genai_client, monkeypatch):
    monkeypatch.delenv("PASSING_SCORE_THRESHOLD", raising=False)
    assert JudgeAgent(project_id="p").pass_threshold == JudgeAgent.DEFAULT_THRESHOLD


# --- LoopAgent gating --------------------------------------------------------
async def test_loop_exits_on_first_pass():
    builder = StubBuilder([VALID_DOC])
    judge = StubJudge(score=90.0)
    loop = LoopAgent(builder=builder, judge=judge, max_iterations=3)

    content, evaluation, snapshots = await loop.execute(topic="raft", research_context={})

    assert content == VALID_DOC
    assert evaluation.passed
    assert judge.calls == 1
    assert len(snapshots) == 1
    assert snapshots[0].format_errors == []


async def test_format_errors_block_convergence_and_feed_next_iteration():
    """A passing judge must not converge content the validator rejects."""
    builder = StubBuilder([NO_CODE_DOC])
    judge = StubJudge(score=95.0)
    loop = LoopAgent(builder=builder, judge=judge, max_iterations=3)

    _, evaluation, snapshots = await loop.execute(topic="raft", research_context={})

    assert evaluation.passed  # the judge was happy...
    assert len(snapshots) == 3  # ...but the loop never converged
    assert snapshots[0].format_errors
    # Structural defects lead the revision list handed to the next build.
    second_call = builder.received_revisions[1]
    assert second_call is not None
    assert any("valid code blocks" in r for r in second_call)
    assert "judge revision" in second_call


async def test_judge_revisions_feed_next_iteration_when_score_is_low():
    builder = StubBuilder([VALID_DOC])
    judge = StubJudge(score=40.0)
    loop = LoopAgent(builder=builder, judge=judge, max_iterations=2)

    _, evaluation, snapshots = await loop.execute(topic="raft", research_context={})

    assert not evaluation.passed
    assert len(snapshots) == 2
    assert builder.received_revisions[0] is None
    assert builder.received_revisions[1] == ["judge revision"]


# --- Judge model call --------------------------------------------------------
class FakeAioModels:
    """Stands in for client.aio.models, the async GenAI surface."""

    def __init__(self, text: str, delay: float = 0.0):
        self.text = text
        self.delay = delay
        self.calls = 0

    async def generate_content(self, model, contents, config):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return SimpleNamespace(text=self.text)


def _fake_client(text: str, delay: float = 0.0) -> tuple[SimpleNamespace, FakeAioModels]:
    aio_models = FakeAioModels(text, delay)
    client = SimpleNamespace(aio=SimpleNamespace(models=aio_models))
    return client, aio_models


def _judge_payload(score: float, decision: str) -> str:
    return json.dumps(
        {
            "overall_score": score,
            "decision": decision,
            "passed": decision == "PASS",
            "strengths": ["s"],
            "weaknesses": ["w"],
            "actionable_revisions": ["r"],
            "criteria_breakdown": [],
        }
    )


async def test_threshold_overrides_model_verdict(no_genai_client):
    """A model that contradicts the threshold does not get the last word."""
    judge = JudgeAgent(project_id="p", pass_threshold=85.0)
    judge.client, _ = _fake_client(_judge_payload(90.0, "FAIL"))

    report = await judge.evaluate(topic="raft", content="# Course")

    assert report.overall_score == 90.0
    assert report.decision is GatingDecision.PASS
    assert report.passed is True


async def test_empty_model_response_raises(no_genai_client):
    """An empty response must fail loudly instead of yielding an invented score."""
    judge = JudgeAgent(project_id="p")
    judge.client, _ = _fake_client("   ")

    with pytest.raises(RuntimeError, match="empty response"):
        await judge.evaluate(topic="raft", content="# Course")


async def test_model_calls_do_not_block_the_event_loop(no_genai_client):
    """
    Two concurrent evaluations must overlap. This fails if the agent ever goes back
    to the synchronous client.models surface, which blocks the whole event loop.
    """
    judge = JudgeAgent(project_id="p")
    judge.client, aio_models = _fake_client(_judge_payload(90.0, "PASS"), delay=0.2)

    started = time.perf_counter()
    await asyncio.gather(
        judge.evaluate(topic="a", content="# A"),
        judge.evaluate(topic="b", content="# B"),
    )
    elapsed = time.perf_counter() - started

    assert aio_models.calls == 2
    assert elapsed < 0.35, f"calls serialized ({elapsed:.2f}s for 2x0.2s of I/O)"


# --- Researcher model call ---------------------------------------------------
RESEARCH_JSON = json.dumps(
    {
        "topic": "raft",
        "executive_summary": "summary",
        "prerequisites": ["python"],
        "core_modules": [
            {
                "module_number": 1,
                "title": "Foundations",
                "objectives": ["quorums"],
                "key_concepts": ["term"],
                "hands_on_lab": "Build a log.",
            }
        ],
        "common_pitfalls": ["split brain"],
        "sources": [],
    }
)


def _grounded_response(text: str, uri: str | None = None):
    chunks = []
    if uri:
        chunks = [SimpleNamespace(web=SimpleNamespace(uri=uri, title="Raft Paper"))]
    candidate = SimpleNamespace(grounding_metadata=SimpleNamespace(grounding_chunks=chunks))
    return SimpleNamespace(text=text, candidates=[candidate])


class FakeResearchModels:
    def __init__(self, response):
        self.response = response

    async def generate_content(self, model, contents, config):
        return self.response


def _attach(agent, response):
    agent.client = SimpleNamespace(aio=SimpleNamespace(models=FakeResearchModels(response)))


async def test_researcher_parses_fenced_json_and_injects_grounding(no_genai_client):
    agent = ResearcherAgent(project_id="p")
    _attach(agent, _grounded_response(f"```json\n{RESEARCH_JSON}\n```", uri="https://raft.github.io"))

    report = await agent.research(topic="raft", focus_areas=["leader election"])

    assert report.topic == "raft"
    assert len(report.core_modules) == 1
    # The model returned no sources, so grounding citations fill the gap.
    assert [s.url for s in report.sources] == ["https://raft.github.io"]


async def test_researcher_leaves_sources_empty_without_grounding(no_genai_client):
    """No grounding metadata means no citations - never an invented one."""
    agent = ResearcherAgent(project_id="p")
    _attach(agent, _grounded_response(RESEARCH_JSON))

    report = await agent.research(topic="raft")

    assert report.sources == []


async def test_researcher_raises_on_malformed_json(no_genai_client):
    """A parse failure must not be replaced by a placeholder syllabus."""
    agent = ResearcherAgent(project_id="p")
    _attach(agent, _grounded_response("I could not produce JSON today."))

    with pytest.raises(json.JSONDecodeError):
        await agent.research(topic="raft")


async def test_researcher_raises_on_empty_response(no_genai_client):
    agent = ResearcherAgent(project_id="p")
    _attach(agent, _grounded_response(""))

    with pytest.raises(RuntimeError, match="empty response"):
        await agent.research(topic="raft")


# --- SequentialAgent ---------------------------------------------------------
def test_zero_iterations_is_rejected_at_construction(no_genai_client):
    with pytest.raises(ValueError, match="at least 1"):
        SequentialAgent(project_id="p", max_iterations=0)


async def test_telemetry_not_converged_when_format_invalid(no_genai_client):
    engine = SequentialAgent(project_id="p", max_iterations=2)
    engine.researcher = StubResearcher()
    builder = StubBuilder([NO_CODE_DOC])
    judge = StubJudge(score=95.0)
    engine.loop_agent = LoopAgent(builder=builder, judge=judge, max_iterations=2)

    result = await engine.run(topic="raft")

    assert result.final_evaluation.passed
    assert result.telemetry.converged is False
    assert result.telemetry.iterations_executed == 2

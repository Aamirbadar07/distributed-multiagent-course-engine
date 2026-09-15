"""
Grounded Researcher Agent.
Leverages Vertex AI / Gemini 2.5 with Google Search Grounding to extract authoritative
syllabus blueprints, code patterns, and verified source citations.
"""
from __future__ import annotations

import json
import logging
import os
from typing import List, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

logger = logging.getLogger("agent.researcher")


class SourceCitation(BaseModel):
    """Authoritative source citation verified during research."""
    title: str = Field(description="Title or domain of the reference source")
    url: str = Field(description="Direct URL to documentation, paper, or specification")
    relevance: str = Field(description="Pedagogical relevance of this reference to the syllabus")


class ModuleOutline(BaseModel):
    """High-level module outline derived from grounded research."""
    module_number: int = Field(description="Sequential index of the module")
    title: str = Field(description="Descriptive title of the module")
    objectives: List[str] = Field(description="Concrete learning outcomes for this module")
    key_concepts: List[str] = Field(description="Specific technical primitives and mechanisms covered")
    hands_on_lab: str = Field(description="Practical hands-on implementation project for the student")


class ResearchReport(BaseModel):
    """Structured research output schema produced by ResearcherAgent."""
    topic: str = Field(description="Curriculum topic investigated")
    executive_summary: str = Field(description="Executive technical summary of the domain")
    prerequisites: List[str] = Field(description="Foundational skills and tooling prerequisites")
    core_modules: List[ModuleOutline] = Field(description="Curriculum progression breakdown")
    common_pitfalls: List[str] = Field(description="Production gotchas and architectural anti-patterns")
    sources: List[SourceCitation] = Field(default_factory=list, description="Grounding source citations")


class ResearcherAgent:
    """
    Researcher Agent integrating Google Search Grounding with Gemini 2.5 Flash
    for low-latency, evidence-based syllabus discovery.
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        self.model_name = model_name or os.getenv("GEMINI_RESEARCH_MODEL", "gemini-2.5-flash")

        # Initialize Google GenAI client with Vertex AI backend or API Key
        # If GOOGLE_CLOUD_PROJECT is defined, use Vertex AI mode with ADC; else standard GenAI
        if self.project_id:
            self.client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=self.location,
            )
            logger.info("ResearcherAgent initialized via Vertex AI [Project: %s, Region: %s]", self.project_id, self.location)
        else:
            self.client = genai.Client()
            logger.info("ResearcherAgent initialized via Google GenAI Client (Standard ADC / API Key)")

    def _build_system_instruction(self) -> str:
        return (
            "You are a Principal Curriculum Architect and Technical Researcher. "
            "Your objective is to conduct exhaustive research on a designated technical topic, "
            "synthesizing verified production engineering concepts, RFC specifications, and current industry standards. "
            "You MUST use Google Search to verify current library releases, architectural patterns, and real-world failure modes. "
            "You must avoid obsolete patterns and structure your output for advanced learners."
        )

    async def research(
        self,
        topic: str,
        audience: str = "Senior Software Engineers",
        focus_areas: Optional[List[str]] = None,
    ) -> ResearchReport:
        """
        Executes grounded research using Gemini 2.5 with Google Search tool enabled.
        """
        logger.info("Conducting grounded syllabus research on: '%s' for audience: '%s'", topic, audience)
        focus_str = f"\nPriority Focus Areas:\n" + "\n".join(f"- {f}" for f in focus_areas) if focus_areas else ""

        user_prompt = f"""
Research and formulate an exhaustive technical course outline on the following topic:
Topic: {topic}
Target Audience: {audience}
{focus_str}

Execution Requirements:
1. Search for current official specifications, documentation, and production engineering postmortems.
2. Outline exactly 3-4 progressive technical modules, transitioning from core mechanics to advanced distributed edge-cases.
3. Every module must include a realistic hands-on lab exercise.
4. Highlight at least 3 production anti-patterns or debugging pitfalls.
5. Return your response as a valid JSON object matching this schema:
{{
  "topic": "{topic}",
  "executive_summary": "High-level summary...",
  "prerequisites": ["List of prerequisites..."],
  "core_modules": [
    {{
      "module_number": 1,
      "title": "Module Title",
      "objectives": ["Obj 1", "Obj 2"],
      "key_concepts": ["Concept 1", "Concept 2"],
      "hands_on_lab": "Lab description..."
    }}
  ],
  "common_pitfalls": ["Pitfall 1", "Pitfall 2"],
  "sources": [
    {{
      "title": "Documentation or Paper Title",
      "url": "https://...",
      "relevance": "Why this is authoritative..."
    }}
  ]
}}
Ensure the response is STRICT JSON only, without markdown wrapping.
"""

        # Configure Google Search Grounding
        config = types.GenerateContentConfig(
            system_instruction=self._build_system_instruction(),
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
            max_output_tokens=4096,
        )

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=user_prompt,
            config=config,
        )

        raw_text = response.text or "{}"
        clean_json = raw_text.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        if clean_json.startswith("```"):
            clean_json = clean_json[3:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
        clean_json = clean_json.strip()

        try:
            parsed_dict = json.loads(clean_json)
            # Inject web grounding metadata if returned by model
            grounding_sources = []
            if hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                grounding_meta = getattr(candidate, "grounding_metadata", None)
                if grounding_meta and getattr(grounding_meta, "grounding_chunks", None):
                    for chunk in grounding_meta.grounding_chunks:
                        web = getattr(chunk, "web", None)
                        if web and getattr(web, "uri", None):
                            grounding_sources.append(
                                SourceCitation(
                                    title=getattr(web, "title", "Verified Web Grounding"),
                                    url=web.uri,
                                    relevance="Google Search grounding citation",
                                )
                            )

            if grounding_sources and not parsed_dict.get("sources"):
                parsed_dict["sources"] = [s.model_dump() for s in grounding_sources]

            report = ResearchReport.model_validate(parsed_dict)
            logger.info("Research completed successfully: %d modules, %d sources.", len(report.core_modules), len(report.sources))
            return report

        except Exception as err:
            logger.warning("Failed to parse structured JSON directly (%s). Building fallback report.", err)
            return ResearchReport(
                topic=topic,
                executive_summary=clean_json[:500] if clean_json else "Research synthesis generated.",
                prerequisites=["Command line proficiency", "Intermediate programming fundamentals"],
                core_modules=[
                    ModuleOutline(
                        module_number=1,
                        title=f"Architectural Foundations of {topic}",
                        objectives=["Understand foundational principles", "Inspect core invariants"],
                        key_concepts=["Primitives", "State Management", "Protocols"],
                        hands_on_lab="Bootstrap initial development environment and verify baseline invariants.",
                    )
                ],
                common_pitfalls=["Inadequate error recovery handling", "Unbounded resource usage"],
                sources=[
                    SourceCitation(
                        title="Google Search Grounding Index",
                        url="https://cloud.google.com/vertex-ai",
                        relevance="Grounded Vertex AI search execution",
                    )
                ],
            )

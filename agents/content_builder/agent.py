"""
Content Builder Agent.
Synthesizes comprehensive, pedagogical markdown courses utilizing researched outlines.
Integrates internal format validation and iteratively addresses Judge feedback.
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional
from google import genai
from google.genai import types
from .format_validator import MarkdownFormatValidator, ValidationResult

logger = logging.getLogger("agent.content_builder")


class ContentBuilderAgent:
    """
    Content Builder Agent using Gemini 2.5 Pro for deep technical writing,
    code synthesis, and pedagogical structuring.
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        self.model_name = model_name or os.getenv("GEMINI_BUILDER_MODEL", "gemini-2.5-pro")
        self.validator = MarkdownFormatValidator()

        if self.project_id:
            self.client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=self.location,
            )
            logger.info("ContentBuilderAgent initialized via Vertex AI [Project: %s]", self.project_id)
        else:
            self.client = genai.Client()
            logger.info("ContentBuilderAgent initialized via Google GenAI Client")

    def _build_system_instruction(self) -> str:
        return (
            "You are a Staff Technical Curriculum Engineer and Master Educator. "
            "Your mission is to generate comprehensive, publication-grade educational modules. "
            "Strict Technical & Formatting Rules: "
            "1. Output MUST be formatted in clean, valid GitHub-Flavored Markdown. "
            "2. Start with a single `# ` H1 heading for the course title. "
            "3. Never skip heading levels (e.g., `# ` -> `## ` -> `### `). "
            "4. All code blocks must specify their language tag (e.g., ```python, ```rust, ```bash). "
            "5. Code must be idiomatic, production-grade, and include comments explaining critical invariants. "
            "6. Embed GitHub-style callouts strategically: `> [!NOTE]`, `> [!TIP]`, `> [!WARNING]`, `> [!IMPORTANT]`. "
            "7. Conclude each module with a dedicated `## Knowledge Check & Hands-on Lab` section containing: "
            "   - 3 conceptual multiple-choice or scenario-based questions with detailed explanations. "
            "   - 1 complete, runnable exercise with instructions. "
            "8. Do not truncate code or summarize with comments like '// implement here'. Write complete snippets."
        )

    async def build(
        self,
        topic: str,
        research_context: Optional[dict] = None,
        critique_revisions: Optional[List[str]] = None,
        iteration: int = 1,
    ) -> str:
        """
        Synthesizes or refines course content based on research and judge feedback.
        """
        logger.info("Building content for topic: '%s' (Iteration %d)", topic, iteration)

        critique_block = ""
        if critique_revisions:
            revisions_text = "\n".join(f"- {r}" for r in critique_revisions)
            critique_block = f"""
CRITICAL REVISIONS REQUIRED FROM AUDIT JUDGE (Iteration {iteration - 1}):
You MUST explicitly address and fix each of these issues in this iteration:
{revisions_text}
"""

        research_block = ""
        if research_context:
            core_mods = research_context.get("core_modules", [])
            sources = research_context.get("sources", [])
            pitfalls = research_context.get("common_pitfalls", [])
            research_block = f"""
GROUNDED CURRICULUM BLUEPRINT:
Topic: {research_context.get('topic', topic)}
Summary: {research_context.get('executive_summary', '')}
Modules to construct:
{core_mods}
Known Production Anti-Patterns to Highlight:
{pitfalls}
Authoritative References to Cite:
{sources}
"""

        prompt = f"""
Generate the complete, publication-grade technical curriculum for:
Topic: {topic}
Iteration: {iteration}

{research_block}
{critique_block}

Produce the full markdown document now. Do not wrap the whole document in an external ```markdown block; output the raw markdown directly.
"""

        config = types.GenerateContentConfig(
            system_instruction=self._build_system_instruction(),
            temperature=0.3,
            max_output_tokens=8192,
        )

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config,
        )

        raw_content = response.text or ""
        # Strip superficial markdown wrappers if model enclosed entire response in ```markdown ... ```
        clean_content = raw_content.strip()
        if clean_content.startswith("```markdown"):
            clean_content = clean_content[11:]
        elif clean_content.startswith("```"):
            clean_content = clean_content[3:]
        if clean_content.endswith("```"):
            clean_content = clean_content[:-3]
        clean_content = clean_content.strip()

        # Run automated format validation tool
        val_result: ValidationResult = self.validator.validate(clean_content)
        if not val_result.is_valid:
            logger.warning("Format validator detected errors: %s", val_result.errors)
        else:
            logger.info("Format validator passed (Words: %d, Code Blocks: %d)",
                        val_result.metrics.get("word_count", 0),
                        val_result.metrics.get("code_blocks", 0))

        return clean_content

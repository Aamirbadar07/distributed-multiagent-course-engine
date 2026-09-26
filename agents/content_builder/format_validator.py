"""
Format Validation Tool Script.
Enforces GitHub-Flavored Markdown specifications, heading hierarchy,
fenced code block language tags, and pedagogical elements (quizzes, alerts).
"""
from __future__ import annotations

import re
from typing import Dict, List
from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    """Validation report returned by the format validator tool."""
    is_valid: bool = Field(description="True if markdown passes all structural requirements")
    errors: List[str] = Field(default_factory=list, description="Critical structural flaws that break parsing")
    warnings: List[str] = Field(default_factory=list, description="Non-critical style or formatting advisories")
    metrics: Dict[str, int] = Field(default_factory=dict, description="Extracted structural metrics")


class MarkdownFormatValidator:
    """Deterministic markdown syntax and curriculum format validator."""

    def __init__(self, min_word_count: int = 500, min_code_blocks: int = 1):
        self.min_word_count = min_word_count
        self.min_code_blocks = min_code_blocks

    def validate(self, markdown_text: str) -> ValidationResult:
        errors: List[str] = []
        warnings: List[str] = []

        if not markdown_text or not markdown_text.strip():
            return ValidationResult(
                is_valid=False,
                errors=["Markdown payload is empty."],
                warnings=[],
                metrics={"word_count": 0, "code_blocks": 0, "headings": 0},
            )

        words = re.findall(r"\b\w+\b", markdown_text)
        word_count = len(words)
        if word_count < self.min_word_count:
            errors.append(
                f"Word count ({word_count}) below mandatory pedagogical minimum ({self.min_word_count})."
            )

        # 1. Heading hierarchy validation
        headings = re.findall(r"^(#{1,6})\s+(.*)$", markdown_text, flags=re.MULTILINE)
        if not headings:
            errors.append("No markdown headings found; document lacks hierarchical structure.")
        else:
            first_level = len(headings[0][0])
            if first_level != 1:
                warnings.append(f"Document does not start with an H1 heading (found H{first_level}).")

            prev_level = first_level
            for hashes, title in headings[1:]:
                current_level = len(hashes)
                if current_level > prev_level + 1:
                    errors.append(
                        f"Skipped heading level from H{prev_level} to H{current_level}: '{title}'"
                    )
                prev_level = current_level

        # 2. Fenced code block validation
        fenced_blocks = re.findall(r"```([a-zA-Z0-9_-]*)\n([\s\S]*?)```", markdown_text)
        total_backtick_blocks = len(re.findall(r"```", markdown_text))
        if total_backtick_blocks % 2 != 0:
            errors.append("Unclosed code block detected: odd number of triple backticks.")

        valid_blocks = 0
        for lang, content in fenced_blocks:
            clean_lang = lang.strip().lower()
            if not clean_lang:
                errors.append("Fenced code block found without explicit language specifier (e.g. ```python).")
            elif not content.strip():
                warnings.append(f"Empty code block detected for language '{clean_lang}'.")
            else:
                valid_blocks += 1

        if valid_blocks < self.min_code_blocks:
            errors.append(
                f"Expected at least {self.min_code_blocks} valid code blocks, found {valid_blocks}."
            )

        # 3. Pedagogical elements (Callouts & Checkpoints)
        has_callout = bool(re.search(r">\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]", markdown_text, re.IGNORECASE))
        if not has_callout:
            warnings.append("Document lacks GitHub-style callouts (> [!NOTE], > [!TIP], etc.).")

        has_quiz = bool(re.search(r"(quiz|knowledge check|self-assessment|checkpoint)", markdown_text, re.IGNORECASE))
        if not has_quiz:
            warnings.append("Document lacks an explicit 'Knowledge Check' or 'Quiz' section.")

        metrics = {
            "word_count": word_count,
            "code_blocks": valid_blocks,
            "headings_count": len(headings),
            "callouts_detected": 1 if has_callout else 0,
        }

        is_valid = len(errors) == 0
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            metrics=metrics,
        )


def validate_markdown_tool(content: str) -> str:
    """Tool invocation wrapper for format validation."""
    validator = MarkdownFormatValidator()
    result = validator.validate(content)
    return result.model_dump_json()

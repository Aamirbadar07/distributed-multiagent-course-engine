---
name: curriculum-deep-research
description: Conducts Google Search-grounded academic and technical syllabus research to produce comprehensive, verified course outlines with technical prerequisites and citations.
metadata:
  version: "1.0.0"
  author: "Principal AI Architecture Team"
  runtime: "python3.11"
  framework: "Google Agent Development Kit (ADK) / Vertex AI"
---

# Deep Research & Grounding Skill

## Purpose
This skill executes grounded web search queries using Google Search to discover current architectural patterns, production best practices, authoritative documentation, and real-world case studies for any designated technical subject. It eliminates hallucinated APIs and outdated syntax by grounding the curriculum directly against authoritative sources.

## Core Capabilities
1. **Dynamic Search Query Generation**: Analyzes high-level course topics and synthesizes targeted, multi-perspective search queries targeting official docs, RFCs, and engineering postmortems.
2. **Authority Filtering**: Filters results prioritizing Tier-1 documentation (e.g., official docs, vendor specifications, peer-reviewed engineering papers) over SEO-farmed summaries.
3. **Structured Pedagogical Extraction**: Transforms raw web search metadata into an interconnected sequence of prerequisites, conceptual modules, hands-on lab exercises, and key terminology.

## Inputs
- `topic` (str): Target domain or technology to research (e.g., "Distributed Systems with Raft Consensus").
- `target_audience` (str): Target proficiency level (e.g., "Senior Software Engineers", "DevOps Practitioners").
- `focus_areas` (list[str], optional): Explicit technical themes to prioritize.

## Execution Rules
- Always enable Google Search grounding through Vertex AI / Google GenAI SDK (`tools=[types.Tool(google_search=types.GoogleSearch())]`).
- Extract exact URL citations and ground truth snippets for every subtopic.
- Identify at least 3 common production failure modes / anti-patterns for inclusion in the curriculum.
- Ensure all API references, library versions, and syntax standards reflect modern stable releases.

## Output Schema
Emits a validated `ResearchReport` containing:
- `topic`: Canonical topic title.
- `executive_summary`: Concise architectural overview.
- `prerequisites`: Required conceptual and operational baselines.
- `core_modules`: List of structured curriculum modules with subtopics and objectives.
- `common_pitfalls`: Real-world anti-patterns and operational gotchas.
- `sources`: List of verified URLs and documentation references with relevance rationales.

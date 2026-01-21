"""
Research Agent
==============

An autonomous research agent that investigates topics using Parallel's
AI-optimized web search and produces comprehensive research reports.

Quick Start:
    from research_agent import research_topic

    # Quick research
    report = research_topic("What is RAG?", depth="quick")
    print(report.executive_summary)

    # Comprehensive research
    report = research_topic("Compare vector databases", depth="comprehensive")
    for finding in report.key_findings:
        print(f"- {finding.statement}")
"""

from .agent import (
    DEPTH_CONFIG,
    ResearchReport,
    create_research_agent,
    research_agent,
    research_topic,
)
from .schemas import Finding, Source

__all__ = [
    "research_agent",
    "create_research_agent",
    "research_topic",
    "ResearchReport",
    "Finding",
    "Source",
    "DEPTH_CONFIG",
]

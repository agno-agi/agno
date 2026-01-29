"""
Code Review Agent
=================

An intelligent code review agent that analyzes pull requests, provides
context-aware suggestions, and enforces coding standards and best practices.
"""

from agent import code_review_agent
from schemas import (
    BugReport,
    CodeReviewResult,
    DocumentationGap,
    FileChange,
    SecurityIssue,
    StyleViolation,
    Suggestion,
    TestRecommendation,
)

__all__ = [
    "code_review_agent",
    # Optional schemas for structured output
    "CodeReviewResult",
    "FileChange",
    "BugReport",
    "SecurityIssue",
    "StyleViolation",
    "Suggestion",
    "TestRecommendation",
    "DocumentationGap",
]

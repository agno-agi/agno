"""
Code Review Schemas
===================

Pydantic models for structured code review analysis, including bug detection,
security issues, style violations, and suggestions.
"""

from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# File Change Schema
# ============================================================================
class FileChange(BaseModel):
    """A file changed in the pull request."""

    filename: str = Field(description="Path to the changed file")
    status: str = Field(description="Change type: added, modified, deleted, renamed")
    additions: int = Field(description="Number of lines added")
    deletions: int = Field(description="Number of lines deleted")
    language: Optional[str] = Field(
        default=None, description="Programming language of the file"
    )
    summary: str = Field(description="Brief summary of changes in this file")


# ============================================================================
# Bug Report Schema
# ============================================================================
class BugReport(BaseModel):
    """A potential bug identified in the code."""

    severity: str = Field(description="Severity: critical, high, medium, low")
    bug_type: str = Field(
        description="Type: logic_error, null_reference, race_condition, resource_leak, off_by_one, infinite_loop, type_error, boundary_error, other"
    )
    location: str = Field(
        description="File and line number(s) where the bug is located"
    )
    description: str = Field(description="Description of the bug")
    code_snippet: Optional[str] = Field(
        default=None, description="Relevant code snippet showing the issue"
    )
    suggested_fix: str = Field(description="Suggested fix for the bug")
    confidence: float = Field(
        description="Confidence in bug detection 0-1", ge=0.0, le=1.0
    )


# ============================================================================
# Security Issue Schema
# ============================================================================
class SecurityIssue(BaseModel):
    """A security vulnerability or concern identified in the code."""

    severity: str = Field(description="Severity: critical, high, medium, low")
    vulnerability_type: str = Field(
        description="Type: sql_injection, xss, csrf, auth_bypass, sensitive_data_exposure, insecure_deserialization, command_injection, path_traversal, hardcoded_credentials, insecure_crypto, other"
    )
    cwe_id: Optional[str] = Field(
        default=None, description="CWE identifier if applicable (e.g., CWE-79)"
    )
    location: str = Field(
        description="File and line number(s) where the issue is located"
    )
    description: str = Field(description="Description of the security issue")
    code_snippet: Optional[str] = Field(
        default=None, description="Relevant code snippet showing the vulnerability"
    )
    remediation: str = Field(description="How to fix the security issue")
    references: list[str] = Field(
        default_factory=list,
        description="Links to relevant security documentation or CVEs",
    )


# ============================================================================
# Style Violation Schema
# ============================================================================
class StyleViolation(BaseModel):
    """A code style or convention violation."""

    severity: str = Field(description="Severity: error, warning, info")
    rule: str = Field(
        description="The style rule violated (e.g., naming-convention, line-length)"
    )
    location: str = Field(
        description="File and line number(s) where the violation is located"
    )
    description: str = Field(description="Description of the style violation")
    suggested_fix: Optional[str] = Field(
        default=None, description="Suggested fix for the violation"
    )


# ============================================================================
# Suggestion Schema
# ============================================================================
class Suggestion(BaseModel):
    """A general code improvement suggestion."""

    category: str = Field(
        description="Category: performance, readability, maintainability, best_practice, simplification, error_handling, logging, documentation, other"
    )
    priority: str = Field(description="Priority: high, medium, low")
    location: str = Field(
        description="File and line number(s) where the suggestion applies"
    )
    description: str = Field(description="Description of the suggestion")
    current_code: Optional[str] = Field(
        default=None, description="Current code snippet"
    )
    suggested_code: Optional[str] = Field(
        default=None, description="Suggested improved code"
    )
    rationale: str = Field(description="Why this improvement is recommended")


# ============================================================================
# Test Recommendation Schema
# ============================================================================
class TestRecommendation(BaseModel):
    """A recommendation for adding or improving tests."""

    test_type: str = Field(
        description="Type: unit, integration, e2e, performance, security"
    )
    priority: str = Field(description="Priority: high, medium, low")
    target: str = Field(
        description="The code being tested (function, class, module, etc.)"
    )
    description: str = Field(description="Description of what should be tested")
    test_scenarios: list[str] = Field(description="Specific test scenarios to cover")
    example_test: Optional[str] = Field(
        default=None, description="Example test code if applicable"
    )


# ============================================================================
# Documentation Gap Schema
# ============================================================================
class DocumentationGap(BaseModel):
    """A missing or inadequate documentation item."""

    doc_type: str = Field(
        description="Type: docstring, readme, api_docs, inline_comment, type_hints, changelog"
    )
    priority: str = Field(description="Priority: high, medium, low")
    location: str = Field(description="File and location where documentation is needed")
    description: str = Field(
        description="What documentation is missing or needs improvement"
    )
    suggested_content: Optional[str] = Field(
        default=None, description="Suggested documentation content"
    )


# ============================================================================
# Code Review Result Schema
# ============================================================================
class CodeReviewResult(BaseModel):
    """Complete structured code review analysis."""

    # PR Summary
    pr_title: Optional[str] = Field(
        default=None, description="Title of the pull request"
    )
    pr_summary: str = Field(
        description="Concise summary of what this PR does and its purpose"
    )
    files_changed: list[FileChange] = Field(
        description="List of files changed with summaries"
    )

    # Overall Assessment
    overall_assessment: str = Field(
        description="Assessment: approve, request_changes, comment"
    )
    assessment_summary: str = Field(
        description="2-3 sentence summary of the review findings"
    )

    # Issues Found
    bugs: list[BugReport] = Field(
        default_factory=list, description="Potential bugs identified"
    )
    security_issues: list[SecurityIssue] = Field(
        default_factory=list, description="Security vulnerabilities found"
    )
    style_violations: list[StyleViolation] = Field(
        default_factory=list, description="Code style violations"
    )

    # Suggestions
    performance_suggestions: list[Suggestion] = Field(
        default_factory=list, description="Performance improvement suggestions"
    )
    code_quality_suggestions: list[Suggestion] = Field(
        default_factory=list, description="Code quality and maintainability suggestions"
    )
    test_recommendations: list[TestRecommendation] = Field(
        default_factory=list, description="Test coverage recommendations"
    )
    documentation_gaps: list[DocumentationGap] = Field(
        default_factory=list, description="Missing or inadequate documentation"
    )

    # Positive Feedback
    highlights: list[str] = Field(
        default_factory=list,
        description="Positive aspects of the code worth highlighting",
    )

    # Metadata
    risk_level: str = Field(description="Overall risk level: high, medium, low")
    estimated_review_time: Optional[str] = Field(
        default=None,
        description="Estimated time for a human to review (e.g., '15 minutes')",
    )
    languages_detected: list[str] = Field(
        default_factory=list, description="Programming languages in the changes"
    )
    confidence: float = Field(
        description="Confidence in review accuracy 0-1", ge=0.0, le=1.0
    )

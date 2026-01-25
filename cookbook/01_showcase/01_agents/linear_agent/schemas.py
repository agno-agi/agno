"""
Linear Project Manager - Output Schemas
=======================================

Pydantic models for structured project management responses.
"""

from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Issue Summary
# ============================================================================
class IssueSummary(BaseModel):
    """Summary of a Linear issue."""

    id: str = Field(description="Linear issue ID")
    title: str = Field(description="Issue title")
    description: Optional[str] = Field(default=None, description="Issue description")
    status: Optional[str] = Field(default=None, description="Current status")
    priority: Optional[int] = Field(
        default=None, description="Priority 0-4, 0 being no priority"
    )
    assignee: Optional[str] = Field(default=None, description="Assigned to")
    url: Optional[str] = Field(default=None, description="Issue URL")


# ============================================================================
# Progress Report
# ============================================================================
class ProgressReport(BaseModel):
    """Progress report for a team or project."""

    team_name: str = Field(description="Team name")
    total_issues: int = Field(description="Total number of issues")
    completed: int = Field(description="Issues completed")
    in_progress: int = Field(description="Issues in progress")
    blocked: int = Field(default=0, description="Issues blocked")
    high_priority_count: int = Field(description="High priority (P1/P2) issues")
    recent_completions: list[str] = Field(
        default_factory=list, description="Recently completed issue titles"
    )
    blockers: list[str] = Field(
        default_factory=list, description="Current blockers or issues needing attention"
    )
    summary: str = Field(description="Executive summary of progress")


# ============================================================================
# Create Issue Result
# ============================================================================
class CreateIssueResult(BaseModel):
    """Result of creating a new issue."""

    success: bool = Field(description="Whether creation succeeded")
    issue_id: Optional[str] = Field(default=None, description="Created issue ID")
    issue_title: str = Field(description="Issue title")
    issue_url: Optional[str] = Field(default=None, description="URL to the issue")
    message: str = Field(description="Success or error message")


# ============================================================================
# Query Result
# ============================================================================
class QueryResult(BaseModel):
    """Result of querying issues."""

    query: str = Field(description="The query that was executed")
    total_found: int = Field(description="Number of issues found")
    issues: list[IssueSummary] = Field(description="List of matching issues")
    summary: str = Field(description="Summary of findings")


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "IssueSummary",
    "ProgressReport",
    "CreateIssueResult",
    "QueryResult",
]

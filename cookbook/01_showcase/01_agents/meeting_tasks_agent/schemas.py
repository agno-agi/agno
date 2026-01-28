"""
Meeting to Linear Tasks Agent - Output Schemas
==============================================

Pydantic models for structured meeting processing responses.
"""

from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Extracted Task
# ============================================================================
class ExtractedTask(BaseModel):
    """An action item extracted from meeting content."""

    description: str = Field(description="Task description")
    owner: Optional[str] = Field(default=None, description="Person responsible")
    deadline: Optional[str] = Field(default=None, description="Due date if mentioned")
    priority: str = Field(
        default="medium", description="Priority: urgent, high, medium, low"
    )
    context: str = Field(description="Surrounding context from meeting")
    confidence: float = Field(
        default=0.8, description="Confidence this is an action item (0-1)"
    )


# ============================================================================
# Created Issue
# ============================================================================
class CreatedIssue(BaseModel):
    """Result of creating a Linear issue from an extracted task."""

    task: ExtractedTask = Field(description="The original extracted task")
    linear_id: Optional[str] = Field(default=None, description="e.g., ENG-456")
    linear_url: Optional[str] = Field(default=None, description="URL to the issue")
    status: str = Field(description="created, skipped, error")
    error_message: Optional[str] = Field(
        default=None, description="Error message if failed"
    )


# ============================================================================
# Meeting Processing Result
# ============================================================================
class MeetingProcessingResult(BaseModel):
    """Complete result of processing a meeting."""

    meeting_title: str = Field(description="Title or topic of the meeting")
    meeting_date: Optional[str] = Field(default=None, description="Date of meeting")
    attendees: list[str] = Field(
        default_factory=list, description="Meeting participants"
    )
    total_tasks_found: int = Field(description="Number of action items identified")
    tasks_created: int = Field(description="Number of Linear issues created")
    tasks_skipped: int = Field(default=0, description="Tasks not created")
    issues: list[CreatedIssue] = Field(
        default_factory=list, description="Created issues"
    )
    meeting_summary: str = Field(description="Brief summary of the meeting")
    next_steps: list[str] = Field(
        default_factory=list, description="Key next steps identified"
    )


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "ExtractedTask",
    "CreatedIssue",
    "MeetingProcessingResult",
]

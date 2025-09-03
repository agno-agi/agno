"""
This example shows how to use complex input types with tools.

Recommendations:
- Specify fields with descriptions, these will be used in the JSON schema sent to the model and will increase accuracy.
- Try not to nest the structures too deeply, the model will have a hard time understanding them.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from agno.agent import Agent
from agno.tools.decorator import tool
from pydantic import BaseModel, Field


# Define Pydantic models for our tools
class UserProfile(BaseModel):
    """User profile information."""

    name: str = Field(..., description="Full name of the user")
    email: str = Field(..., description="Valid email address")
    age: int = Field(..., ge=0, le=120, description="Age of the user")
    interests: List[str] = Field(
        default_factory=list, description="List of user interests"
    )
    created_at: datetime = Field(
        default_factory=datetime.now, description="Account creation timestamp"
    )


class TaskPriority(str, Enum):
    """Priority levels for tasks."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Task(BaseModel):
    """Task information."""

    title: str = Field(..., min_length=1, max_length=100, description="Task title")
    description: Optional[str] = Field(None, description="Detailed task description")
    priority: TaskPriority = Field(
        default=TaskPriority.MEDIUM, description="Task priority level"
    )
    due_date: Optional[datetime] = Field(None, description="Task due date")
    assigned_to: Optional[UserProfile] = Field(
        None, description="User assigned to the task"
    )


# Custom tools using Pydantic models
@tool
def create_user(user_data: UserProfile) -> str:
    """Create a new user profile with validated information."""
    # In a real application, this would save to a database
    return f"Created user profile for {user_data.name} with email {user_data.email}"


@tool
def create_task(task_data: Task) -> str:
    """Create a new task with priority and assignment."""
    # In a real application, this would save to a database
    return f"Created task '{task_data.title}' with priority {task_data.priority}"


# Create the agent
agent = Agent(
    name="task_manager",
    description="An agent that manages users and tasks with proper validation",
    tools=[create_user, create_task],
)

# Example usage
if __name__ == "__main__":
    # Example 1: Create a user
    agent.print_response(
        "Create a new user named John Doe with email john@example.com, age 30, and interests in Python and AI"
    )

    # Example 2: Create a task
    agent.print_response(
        "Create a high priority task titled 'Implement API endpoints' due tomorrow"
    )

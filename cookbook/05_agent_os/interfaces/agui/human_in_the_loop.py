"""
Human in the Loop — Dojo Demo
==============================

HITL tool: generate_task_steps (requires_confirmation)

Dojo expects generate_task_steps that returns:
- steps: list of {description: str, status: "enabled"|"disabled"|"executing"}

The frontend renders a step selector UI where user can toggle steps and confirm/reject.
"""

from typing import List

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools import tool
from pydantic import BaseModel, Field


class TaskStep(BaseModel):
    description: str = Field(description="Description of the step")
    status: str = Field(
        default="enabled", description="Status: enabled, disabled, or executing"
    )


@tool(requires_confirmation=True)
def generate_task_steps(steps: List[TaskStep]) -> str:
    """Generate a list of task steps for the user to review and confirm.

    The frontend will display these steps with checkboxes.
    User can enable/disable steps before confirming execution.
    """
    enabled_steps = [s for s in steps if s.status == "enabled"]
    return f"Executing {len(enabled_steps)} steps: " + ", ".join(
        s.description for s in enabled_steps
    )


hitl_agent = Agent(
    name="human_in_the_loop",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file="/tmp/agui_human_in_the_loop.db"),
    tools=[generate_task_steps],
    instructions="""You help users plan tasks that require confirmation.

When asked to plan something (trip, recipe, project, etc.):
1. Break it down into clear steps (5-10 steps typically)
2. Use the generate_task_steps tool with a list of steps
3. Each step should have a description and status="enabled"

Example: For "plan a trip to Paris", create steps like:
- Book flights
- Reserve hotel
- Plan activities
- Pack luggage
- etc.

The user will review and confirm which steps to execute.""",
    markdown=True,
)

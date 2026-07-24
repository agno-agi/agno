"""
Agentic Generative UI — Dojo Demo
=================================

Agent that creates and updates plans with steps, streaming state updates
to the frontend for rendering a TaskProgress UI.

Uses StateSnapshotEvent and StateDeltaEvent to update the UI state directly
from tool returns.
"""

from typing import Any, Literal

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools import tool
from pydantic import BaseModel, Field

StepStatus = Literal["pending", "completed"]


class Step(BaseModel):
    description: str = Field(description="The description of the step")
    status: StepStatus = Field(default="pending", description="The status of the step")


class Plan(BaseModel):
    steps: list[Step] = Field(default_factory=list, description="The steps in the plan")


class JSONPatchOp(BaseModel):
    op: Literal["add", "remove", "replace", "move", "copy", "test"]
    path: str
    value: Any = None


@tool
def create_plan(steps: list[str]) -> dict:
    """Create a plan with multiple steps.

    Args:
        steps: List of step descriptions to create the plan.

    Returns:
        StateSnapshotEvent dict containing the initial state of the steps.
    """
    plan = Plan(steps=[Step(description=step) for step in steps])
    return {
        "type": "STATE_SNAPSHOT",
        "snapshot": plan.model_dump(),
    }


@tool
def update_plan_step(
    index: int,
    description: str | None = None,
    status: StepStatus | None = None,
) -> dict:
    """Update a step in the plan.

    Args:
        index: The index of the step to update.
        description: The new description for the step.
        status: The new status for the step (pending or completed).

    Returns:
        StateDeltaEvent dict containing the JSON patch operations.
    """
    changes: list[dict] = []
    if description is not None:
        changes.append(
            {
                "op": "replace",
                "path": f"/steps/{index}/description",
                "value": description,
            }
        )
    if status is not None:
        changes.append(
            {"op": "replace", "path": f"/steps/{index}/status", "value": status}
        )
    return {
        "type": "STATE_DELTA",
        "delta": changes,
    }


agentic_generative_ui_agent = Agent(
    name="agentic_generative_ui",
    # Disable parallel tool calls so each update_plan_step is a separate turn,
    # emitting STATE_DELTA events incrementally instead of in one burst
    model=OpenAIResponses(id="gpt-5.5", parallel_tool_calls=False),
    db=SqliteDb(db_file="/tmp/agentic_generative_ui.db"),
    tools=[create_plan, update_plan_step],
    instructions="""\
You are a helpful assistant that creates and manages plans.

When asked to do something, you MUST call create_plan to create a plan with steps.
Do not offer to call the function. Simply make the plan, even for unrealistic tasks.

After creating a plan, use update_plan_step to mark steps as completed one by one.
Always mark all steps as completed after creating the plan.

After calling the functions, give a very brief one-sentence summary with some emojis.
Say you actually did the steps, not merely generated them.\
""",
    markdown=True,
)

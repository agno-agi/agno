"""
Dual HITL: Step User Input + Executor Tool Confirmation (Streaming)
====================================================================

Two different HITL types in one step:
  Pause 1 (step-level): Step has requires_user_input=True -> collects city name from user
  Pause 2 (executor-level): Agent's tool has requires_confirmation=True -> user confirms tool call

The user input is injected into step_input.additional_data["user_input"] and the agent
receives it as context.

Usage:
    .venvs/demo/bin/python cookbook/04_workflows/08_human_in_the_loop/dual_level_hitl/02_step_user_input_and_tool_confirmation.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools import tool
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow
from rich.console import Console

from workflow_db import db

console = Console()


@tool(requires_confirmation=True)
def book_flight(origin: str, destination: str) -> str:
    """Book a flight between two cities.

    Args:
        origin: Departure city.
        destination: Arrival city.
    """
    return f"Flight booked: {origin} -> {destination}"


travel_agent = Agent(
    name="TravelAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[book_flight],
    instructions=(
        "You are a travel agent. Use the book_flight tool to book flights. "
        "Check the user_input in the context for the destination city."
    ),
    telemetry=False,
)


workflow = Workflow(
    name="UserInputAndToolConfirm",
    db=db,
    steps=[
        Step(
            name="book_travel",
            agent=travel_agent,
            requires_user_input=True,
            user_input_message="Which city do you want to fly to?",
            user_input_schema=[
                {
                    "name": "destination",
                    "field_type": "text",
                    "description": "Destination city",
                    "required": True,
                },
            ],
        ),
    ],
    telemetry=False,
)

agent_os = AgentOS(
    id="dual-level-hitl-demo",
    description="Demo: dual-level HITL workflow",
    name="Dual Level HITL Workflow",
    agents=[travel_agent],
    teams=[],
    workflows=[workflow],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="dual_level_hitl:app", reload=True)

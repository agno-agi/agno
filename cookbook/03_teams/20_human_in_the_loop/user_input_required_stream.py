"""Team HITL Streaming: Member agent tool requiring user input.

This example demonstrates how a team pauses when a member agent's tool
needs additional information from the user before it can be executed
in streaming mode.

Note: When streaming with member agents, use isinstance() with TeamRunPausedEvent
to distinguish the team's pause from member agent pauses.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.team.team import Team
from agno.tools import tool
from agno.utils import pprint

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/team_hitl_stream.db")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@tool(requires_user_input=True, user_input_fields=["passenger_name"])
def book_flight(destination: str, date: str, passenger_name: str) -> str:
    """Book a flight to a destination.

    Args:
        destination (str): The destination city
        date (str): Travel date
        passenger_name (str): Full name of the passenger
    """
    return f"Booked flight to {destination} on {date} for {passenger_name}"


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
booking_agent = Agent(
    name="Booking Agent",
    role="Books travel arrangements",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[book_flight],
    instructions="You MUST call the book_flight tool immediately with whatever information you have. Do NOT ask clarifying questions - the tool will pause and request any missing information from the user.",
    db=db,
)


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Travel Team",
    members=[booking_agent],
    model=OpenAIResponses(id="gpt-5.2"),
    instructions="Delegate all booking requests to the Booking Agent immediately.",
    db=db,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for run_event in team.run("Book a flight to Tokyo for next Friday", stream=True):
        if isinstance(run_event, TeamRunPausedEvent):
            for req in run_event.active_requirements:
                print(f"  needs_user_input: {req.needs_user_input}")
                print(f"  needs_confirmation: {req.needs_confirmation}")
                if req.needs_user_input:
                    print(f"  Tool: {req.tool_execution.tool_name}")
                    for field in req.user_input_schema or []:
                        print(f"  Field needed: {field.name} - {field.description}")

                    req.provide_user_input({"passenger_name": "John Smith"})

            print("Continuing run...")
            response = team.continue_run(
                run_id=run_event.run_id,
                session_id=run_event.session_id,
                requirements=run_event.requirements,
                stream=True,
            )
            pprint.pprint_run_response(response)

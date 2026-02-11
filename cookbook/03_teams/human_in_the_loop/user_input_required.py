"""Team HITL: Member agent tool requiring user input.

This example demonstrates how a team pauses when a member agent's tool
needs additional information from the user before it can be executed.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools import tool


@tool(requires_user_input=True, user_input_fields=["passenger_name"])
def book_flight(destination: str, date: str, passenger_name: str) -> str:
    """Book a flight to a destination.

    Args:
        destination (str): The destination city
        date (str): Travel date
        passenger_name (str): Full name of the passenger
    """
    return f"Booked flight to {destination} on {date} for {passenger_name}"


booking_agent = Agent(
    name="Booking Agent",
    role="Books travel arrangements",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[book_flight],
)

team = Team(
    name="Travel Team",
    members=[booking_agent],
    model=OpenAIChat(id="gpt-4o-mini"),
)

response = team.run("Book a flight to Tokyo for next Friday")

if response.is_paused:
    print("Team paused - requires user input")
    for req in response.requirements:
        if req.needs_user_input:
            print(f"  Tool: {req.tool_execution.tool_name}")
            for field in req.user_input_schema or []:
                print(f"  Field needed: {field.name} - {field.description}")

            req.provide_user_input({"passenger_name": "John Smith"})

    response = team.continue_run(response)
    print(f"Result: {response.content}")
else:
    print(f"Result: {response.content}")

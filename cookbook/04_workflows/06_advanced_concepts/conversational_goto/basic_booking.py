"""
Conversational Sticky Steps + Goto
==================================

Ticket-booking style workflow demonstrating:
1. conversational=True sticky multi-turn chat on an agent step
2. complete_step() to advance when the agent is done collecting info
3. goto() to jump back to an earlier host step and re-run it with the
   current user message

Requires an OpenAI API key. Uses gpt-5.5 via OpenAIResponses.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

db = SqliteDb(db_file="tmp/conversational_booking.db")

destination_agent = Agent(
    name="Destination Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "You collect the travel destination.",
        "Ask clarifying questions until the destination is clear.",
        "When done, call complete_step(destination='...') with the destination.",
        "If the user wants to change something already collected earlier, use goto.",
        "Speak naturally to the user; do not dump JSON in your replies.",
    ],
    markdown=True,
)

departure_agent = Agent(
    name="Departure Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "You collect the departure time given the destination from the previous step.",
        "Ask clarifying questions until the departure time is clear.",
        "When done, call complete_step(departure_time='...').",
        "If the user wants to change the destination, call goto('destination', clear_keys=[...]).",
        "Speak naturally to the user; do not dump JSON in your replies.",
    ],
    markdown=True,
)

booking_agent = Agent(
    name="Booking Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "Place a mock booking using destination and departure time from previous steps.",
        "Confirm the booking details to the user.",
    ],
    markdown=True,
)

booking_workflow = Workflow(
    name="Conversational Booking",
    db=db,
    steps=[
        Step(
            name="destination",
            agent=destination_agent,
            conversational=True,
            description="Collect travel destination",
        ),
        Step(
            name="departure",
            agent=departure_agent,
            conversational=True,
            description="Collect departure time",
        ),
        Step(
            name="booking",
            agent=booking_agent,
            description="Place the booking",
        ),
    ],
    add_session_state_to_context=True,
)


if __name__ == "__main__":
    session_id = "booking-demo"

    print("=== Turn 1: start booking ===")
    r1 = booking_workflow.run("I want to book a ticket", session_id=session_id)
    print("status:", r1.status)
    print("pause_kind:", r1.pause_kind)
    print("content:", r1.content)
    print()

    print("=== Turn 2: provide destination ===")
    r2 = booking_workflow.run("Shanghai Hongqiao", session_id=session_id)
    print("status:", r2.status)
    print("paused_step:", r2.paused_step_name)
    print("content:", r2.content)
    print()

    print("=== Turn 3: change destination mid-departure ===")
    r3 = booking_workflow.run(
        "Actually change the destination to Hangzhou",
        session_id=session_id,
    )
    print("status:", r3.status)
    print("paused_step:", r3.paused_step_name)
    print("content:", r3.content)

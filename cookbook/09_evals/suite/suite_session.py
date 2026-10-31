"""
Eval Suite: Session State and Multi-Turn Cases
==============================================

Pass session_state and user_id to the run, continue one session across several
turns to check a multi-turn conversation, and send an image with a turn.

python cookbook/09_evals/suite/suite_session.py                 # run all cases
python cookbook/09_evals/suite/suite_session.py --list          # list cases
python cookbook/09_evals/suite/suite_session.py --name books_the_chosen_slot
python cookbook/09_evals/suite/suite_session.py --json-output tmp/evals.json
"""

import sys
from typing import Any

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.eval import Case, CaseResult, cli
from agno.media import Image
from agno.models.message import Message
from agno.models.openai import OpenAIResponses
from agno.run import RunContext, RunStatus


# ---------------------------------------------------------------------------
# Create Tools
# ---------------------------------------------------------------------------
def get_open_slots(run_context: RunContext) -> str:
    """Return the open appointment slots on the caller's calendar."""
    if run_context.session_state is None:
        run_context.session_state = {}
    session_state = run_context.session_state
    if not session_state.get("calendar_id"):
        return "No calendar is configured for this caller."
    return f"Open slots ({session_state['timezone']}): Tuesday 10:00, Wednesday 15:00"


def create_appointment(run_context: RunContext, slot: str, name: str) -> str:
    """Book the given slot for the caller.

    Args:
        slot: The slot to book, as returned by get_open_slots.
        name: The caller's name.
    """
    if run_context.session_state is None:
        run_context.session_state = {}
    session_state = run_context.session_state
    session_state["appointment"] = {"slot": slot, "name": name}
    return f"Booked {slot} for {name} on calendar {session_state.get('calendar_id')}."


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# The db and add_history_to_context let a turn read the earlier turns of its session.
agent = Agent(
    id="sales-setter",
    model=OpenAIResponses(id="gpt-5.5"),
    db=InMemoryDb(),
    add_history_to_context=True,
    tools=[get_open_slots, create_appointment],
    instructions=[
        "You book sales calls. Use get_open_slots to offer times.",
        "Once the caller has given their name and picked a slot, call create_appointment.",
    ],
)

# ---------------------------------------------------------------------------
# Create Hooks
# ---------------------------------------------------------------------------
booking_session_id = "booking-1"
calendar = {"calendar_id": "cal-1", "timezone": "UTC"}


async def run_earlier_turns() -> None:
    """Run the first turn of the booking conversation in the session the case continues."""
    run_output = await agent.arun(
        "Hi, I'm Priya. I'd like to book a call. What times do you have?",
        session_id=booking_session_id,
        user_id="lead-42",
        # Copied: the run writes into the session_state it is handed
        session_state=dict(calendar),
    )
    # A failed run is returned, not raised
    if run_output.status != RunStatus.completed:
        raise RuntimeError(f"earlier turn ended with status {run_output.status.value}")


async def delete_booking_session(context: Any, result: CaseResult) -> None:
    """Remove the session so a db that outlives the process starts the next run clean."""
    await agent.adelete_session(session_id=booking_session_id, user_id="lead-42")


# ---------------------------------------------------------------------------
# Declare Cases
# ---------------------------------------------------------------------------
# The second case continues the session its setup hook started. The last case sends an
# image with its turn by giving a Message as the input.
CASES = (
    Case(
        name="offers_open_slots",
        agent=agent,
        input="Hi, I'm Priya. I'd like to book a call. What times do you have?",
        criteria="Offers Tuesday 10:00 and Wednesday 15:00.",
        expected_tool_calls=("get_open_slots",),
        user_id="lead-42",
        session_state=calendar,
    ),
    Case(
        name="books_the_chosen_slot",
        agent=agent,
        input="Wednesday at 15:00 works for me.",
        criteria="Confirms that the Wednesday 15:00 call is booked.",
        expected_tool_calls=("create_appointment",),
        setup=run_earlier_turns,
        teardown=delete_booking_session,
        session_id=booking_session_id,
        user_id="lead-42",
    ),
    Case(
        name="no_calendar_no_slots",
        agent=agent,
        input="What times do you have for a call?",
        criteria="Does not offer any specific time slot.",
    ),
    Case(
        name="offers_slots_for_the_pictured_venue",
        agent=agent,
        input=Message(
            role="user",
            content="I'd like to book a call about a tour of this landmark. Which one is it, and what times do you have?",
            images=[
                Image(
                    url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
                )
            ],
        ),
        criteria="Names the Golden Gate Bridge and offers Tuesday 10:00 and Wednesday 15:00.",
        expected_tool_calls=("get_open_slots",),
        user_id="lead-42",
        session_state=calendar,
    ),
)

# ---------------------------------------------------------------------------
# Run Suite
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sys.exit(cli(CASES))

"""
Member Tool Hooks
=================

Demonstrates permission-aware tool hooks that gate member delegation.
"""

from typing import Any, Callable

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run import RunContext
from agno.team import Team, TeamMode

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
CUSTOMER_PERMISSIONS = {
    "cust_1001": ["view", "edit"],
    "cust_1002": ["view"],
}

CUSTOMER_MEDICAL_DATA = {
    "cust_1001": {
        "name": "John Doe",
        "age": 30,
        "medical_history": "Asthma diagnosed at age 12. Appendectomy at age 22.",
        "medications": "Albuterol inhaler as needed",
        "allergies": "Penicillin",
        "family_history": "Father: hypertension; Mother: type 2 diabetes",
        "current_medications": "Albuterol inhaler",
    },
    "cust_1002": {
        "name": "Jane Doe",
        "age": 25,
        "medical_history": "Seasonal allergies. Fractured left wrist at age 16.",
        "medications": "Cetirizine during spring",
        "allergies": "Peanuts, latex",
        "family_history": "Mother: breast cancer; Sibling: asthma",
        "current_medications": "Cetirizine",
    },
}


def get_medical_data(customer_id: str) -> dict[str, Any]:
    """Get medical data for a customer."""
    return CUSTOMER_MEDICAL_DATA[customer_id]


def set_current_medications(customer_id: str, medications: str) -> dict[str, Any]:
    """Set the current medications for a customer."""
    CUSTOMER_MEDICAL_DATA[customer_id]["current_medications"] = medications
    return CUSTOMER_MEDICAL_DATA[customer_id]


def set_family_history(customer_id: str, family_history: str) -> dict[str, Any]:
    """Set the family history for a customer."""
    CUSTOMER_MEDICAL_DATA[customer_id]["family_history"] = family_history
    return CUSTOMER_MEDICAL_DATA[customer_id]


def member_input_hook(
    function_name: str,
    function_call: Callable,
    arguments: dict[str, Any],
    run_context: RunContext,
):
    """Verify user permissions before delegating to member agents."""
    if run_context.session_state is None:
        run_context.session_state = {}

    if function_name == "delegate_task_to_member":
        member_id = arguments.get("member_id")
        customer_id = run_context.session_state.get("current_user_id")

        if customer_id not in CUSTOMER_PERMISSIONS:
            raise Exception("Customer not found")

        if (
            member_id == "medical-writer-agent"
            and "edit" not in CUSTOMER_PERMISSIONS[customer_id]
        ):
            raise Exception("Customer does not have edit permissions")

        if (
            member_id == "medical-reader-agent"
            and "view" not in CUSTOMER_PERMISSIONS[customer_id]
        ):
            raise Exception("Customer does not have view permissions")

    result = function_call(**arguments)
    return result


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
medical_reader_agent = Agent(
    name="Medical Reader Agent",
    id="medical-reader-agent",
    role="Read medical data",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[get_medical_data],
    instructions=[
        "Read medical data",
    ],
)

medical_writer_agent = Agent(
    name="Medical Writer Agent",
    id="medical-writer-agent",
    role="Write medical data",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[set_current_medications, set_family_history],
    instructions=[
        "Write medical data",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
medical_team = Team(
    name="Company Info Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[medical_reader_agent, medical_writer_agent],
    markdown=True,
    instructions=[
        "You are a team that has access to medical data.",
        "Answer user questions about the medical data.",
        "Current user ID is {current_user_id}",
    ],
    show_members_responses=True,
    mode=TeamMode.route,
    tool_hooks=[member_input_hook],
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    medical_team.print_response(
        "What are my current medications?",
        user_id="cust_1001",
        stream=True,
    )
    medical_team.print_response(
        "Update my current medications to 'Cetirizine'",
        user_id="cust_1001",
        stream=True,
    )

    medical_team.print_response(
        "What are my family history?",
        user_id="cust_1002",
        stream=True,
    )
    medical_team.print_response(
        "Update my family history to 'Father: hypertension'",
        user_id="cust_1002",
        stream=True,
    )

"""
Stream a custom tool event through AgentOS
==========================================

An async tool yields a ``CustomEvent`` populated from request session state.
Serving the agent through AgentOS turns that event into the same SSE surface as
built-in run events. The client sends session state, consumes the stream, and
asserts the custom customer-profile event arrived.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/06_customize/custom_events.py
Try: Run this file with --demo in another terminal
"""

import argparse
import json
from dataclasses import dataclass
from typing import Optional

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.run import RunContext
from agno.run.agent import CustomEvent
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create Custom Event AgentOS
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
AGENT_ID = "customer-profile-agent"


@dataclass
class CustomerProfileEvent(CustomEvent):
    """Carry customer profile fields as one custom run event."""

    customer_name: Optional[str] = None
    customer_email: Optional[str] = None


@tool()
async def get_customer_profile(run_context: RunContext):
    """Yield the customer profile supplied in AgentOS session state."""
    session_state = run_context.session_state or {}
    yield CustomerProfileEvent(
        customer_name=session_state.get("customer_name", "Unknown"),
        customer_email=session_state.get("customer_email", "unknown@example.com"),
    )


db = SqliteDb(
    id="custom-events-db",
    db_file="tmp/agent_os_custom_events.db",
)

profile_agent = Agent(
    id=AGENT_ID,
    name="Customer Profile Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[get_customer_profile],
    instructions=(
        "When asked for the current customer profile, call "
        "get_customer_profile immediately."
    ),
)

agent_os = AgentOS(
    id="custom-events-os",
    db=db,
    agents=[profile_agent],
)
app = agent_os.get_app()


def run_demo() -> None:
    """Stream one run and verify the custom event crossed the OS boundary."""
    custom_event: dict | None = None
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        with client.stream(
            "POST",
            f"/agents/{AGENT_ID}/runs",
            data={
                "message": "Get the current customer profile.",
                "session_id": "custom-events-demo",
                "session_state": json.dumps(
                    {
                        "customer_name": "Ada Lovelace",
                        "customer_email": "ada@example.com",
                    }
                ),
                "stream": "true",
            },
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if (
                    event.get("event") == "CustomEvent"
                    and event.get("customer_email") == "ada@example.com"
                ):
                    custom_event = event

    if custom_event is None:
        raise RuntimeError("The SSE stream did not contain CustomerProfileEvent")
    print(
        "Custom event: "
        f"{custom_event['customer_name']} <{custom_event['customer_email']}>"
    )


# ---------------------------------------------------------------------------
# Run Custom Event AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the HTTP client against a server already listening on port 7777.",
    )
    args = parser.parse_args()

    if args.demo:
        run_demo()
    else:
        agent_os.serve(app=app, port=7777)

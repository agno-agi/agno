"""
Return a Hand-Authored A2UI Surface over AG-UI
==============================================

The other way to put a rendered surface on screen: an ordinary backend tool
whose result is the surface itself. The component tree is written here, once, so
only the data changes per call. No second model designs anything, so there is
nothing to validate, retry, or stream, and no extra tokens are spent.

Reach for this when you know what the card looks like and the agent only chooses
when to show it and what to put in it. Reach for `a2ui_generated_ui.py` when the
layout itself has to be decided per question.

The client renders whatever it finds under `a2ui_operations` in a tool result, so
the component names below have to exist in the catalog the client registered,
and `CATALOG_ID` has to be that catalog's id.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/a2ui_fixed_schema.py
Try: ask for a flight at http://localhost:7777/fixed-schema/agui
"""

import json

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools import tool

# ---------------------------------------------------------------------------
# Author the Surface
# ---------------------------------------------------------------------------

# Must match the catalog id the client registered with its renderer.
CATALOG_ID = "flight-card-catalog"
SURFACE_ID = "flight-card"

# Values are bound to data paths rather than written in, so one tree serves
# every flight and only the data model changes per call.
FLIGHT_CARD = [
    {"id": "root", "component": "Card", "child": "body"},
    {"id": "body", "component": "Column", "children": ["route", "times", "price"]},
    {"id": "route", "component": "Text", "text": {"path": "/route"}},
    {"id": "times", "component": "Text", "text": {"path": "/times"}},
    {"id": "price", "component": "Text", "text": {"path": "/price"}},
]

db = SqliteDb(
    id="agui-a2ui-fixed-db",
    db_file="tmp/agui_a2ui_fixed.db",
)


@tool
def show_flight(route: str, times: str, price: str) -> str:
    """Show a flight to the user as a card.

    Args:
        route: Origin and destination, for example "SFO to JFK".
        times: Departure and arrival, for example "08:15 to 16:40".
        price: Fare including currency, for example "USD 412".
    """
    return json.dumps(
        {
            "a2ui_operations": [
                {
                    "version": "v0.9",
                    "createSurface": {"surfaceId": SURFACE_ID, "catalogId": CATALOG_ID},
                },
                {
                    "version": "v0.9",
                    "updateComponents": {
                        "surfaceId": SURFACE_ID,
                        "components": FLIGHT_CARD,
                    },
                },
                {
                    "version": "v0.9",
                    "updateDataModel": {
                        "surfaceId": SURFACE_ID,
                        "path": "/",
                        "value": {"route": route, "times": times, "price": price},
                    },
                },
            ]
        }
    )


# ---------------------------------------------------------------------------
# Create Flight Agent
# ---------------------------------------------------------------------------

flight_agent = Agent(
    id="agui-a2ui-fixed-agent",
    name="AG-UI Flight Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    # The AG-UI interface passes only the latest user message as input, so this
    # is what gives the agent its earlier turns. Without it a follow-up such as
    # "what about the morning flight" arrives with no memory of the card that
    # was just shown, and the db above stores a history nothing reads.
    add_history_to_context=True,
    tools=[show_flight],
    instructions=[
        "Help the user find a flight.",
        "Call show_flight to present a specific flight rather than describing it.",
        "Invent plausible times and fares; this example has no booking backend.",
    ],
)

agent_os = AgentOS(
    id="agui-a2ui-fixed-os",
    description="AgentOS returning a hand-authored A2UI surface over AG-UI.",
    agents=[flight_agent],
    interfaces=[AGUI(agent=flight_agent, prefix="/fixed-schema")],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Fixed-Schema Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)

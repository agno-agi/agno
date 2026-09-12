"""
Interrupt and resume over AG-UI
===============================

A paused Agno run is an AG-UI interrupt. By default the pause reaches the client
as the pending tool call the pause itself reported, and the run terminal says
nothing about the run waiting, which is what released clients already expect: a
pause and a completion look the same on it. Set emit_interrupt_outcome=True, the
boolean this file turns on for one of its two mounts, and the same terminal
carries outcome={"type": "interrupt", "interrupts": [...]}, one entry per
requirement the pause left open rather than per pending call it showed, each
naming the call it is bound to where that call had an id of its own and, where
the pause has an answer shape to describe, the JSON Schema of the answer it
wants. A requirement whose call carried no id is still open and still answerable
under its own interrupt id, so it is advertised without one. An answer that
comes back is held to that same schema. An external execution describes none:
the client runs the tool and hands back whatever that tool returned.

The answers come back in the resume array of the next request, keyed by
interrupt id, and the paused run continues from them rather than restarting.
That array is read whether or not the outcome is emitted, so accepting it does
not depend on the setting. Filling it does: no interrupt id reaches the wire
unless the outcome carries it, so a client on the quiet mount has no id to key
an entry by and resolves the pause through the older channel's trailing tool
message instead.

Both settings serve the same agent, so the two terminals can be compared side by
side. Give each mount its own threadId, because a threadId becomes the Agno
session id and reusing one continues the other mount's session.

Prerequisites: OPENAI_API_KEY, and ag-ui-protocol 0.1.19 or newer, the release
     the interrupt-aware run lifecycle this file asks for arrived in. Naming the
     Team member an interrupt was raised inside needs the later release the
     README states; this file serves a single agent and needs no part of that.
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/interrupt_round_trip.py
Try: POST to http://localhost:7777/interrupts/agui, read the interrupt ids off
     RUN_FINISHED, then POST the same body again on the same threadId with one
     field added: "resume": [{"interruptId": "<id>", "status": "resolved",
     "payload": {"accepted": true}}]. One array answers every interrupt the
     outcome carried, so a request naming two recipients pauses on two calls and
     takes two entries: answering one of them is refused as a partial resume,
     naming the ids left open. Every field a RunAgentInput requires has to be
     there in that second request too, or it is refused before the resume is
     read at all. Those are threadId, runId, messages, tools, context and
     forwardedProps on every release this file runs on, and state as well on the
     releases that still required it, which a later one made optional, so
     sending all seven is what works across the range; the README's Resuming
     section shows both requests in full. A second threadId is a second Agno
     session, so it starts a new run instead of resuming the paused one.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create Confirmation Tool and Agent
# ---------------------------------------------------------------------------


@tool(requires_confirmation=True)
def send_email(to: str, subject: str, body: str) -> str:
    """Simulate sending one email after a user confirms its contents."""
    return f"Email sent to {to} with subject '{subject}'."


db = SqliteDb(
    id="agui-interrupt-db",
    db_file="tmp/agui_interrupt_round_trip.db",
)

email_agent = Agent(
    id="agui-interrupt-agent",
    name="AG-UI Interrupt Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    tools=[send_email],
    instructions=[
        (
            "For every email request, call send_email immediately with the "
            "recipient, subject, and body."
        ),
        (
            "Do not ask for confirmation in prose. AgentOS pauses the tool call "
            "and lets the AG-UI client collect the confirmation."
        ),
        "Never claim send_email ran before its tool result is available.",
        "After a confirmed call, report the recipient and subject in one sentence.",
    ],
)

agent_os = AgentOS(
    id="agui-interrupt-os",
    description="The AG-UI interrupt round trip, with and without the typed outcome.",
    agents=[email_agent],
    interfaces=[
        AGUI(agent=email_agent, prefix="/interrupts", emit_interrupt_outcome=True),
        AGUI(agent=email_agent, prefix="/interrupts-quiet"),
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Interrupt Round Trip Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)

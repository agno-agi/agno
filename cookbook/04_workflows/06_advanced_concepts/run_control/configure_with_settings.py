"""
Configure With Settings
=======================

Configure a Workflow with settings dataclasses instead of flat parameters.

Workflow supports the session, event and debug settings groups. The resulting
workflow is identical to one built with the flat parameters, and the flat
parameters keep working as before. If a parameter is set both ways, the
settings object wins and a warning is logged if the values differ.
"""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.settings import DebugSettings, EventSettings, SessionSettings
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
answer_agent = Agent(
    name="Answer Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Answer in one short sentence.",
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Settings Workflow",
    db=InMemoryDb(),
    steps=[Step(name="answer", agent=answer_agent)],
    session_settings=SessionSettings(
        session_id="settings-demo",
        cache_session=True,
    ),
    event_settings=EventSettings(
        store_events=True,
    ),
    debug_settings=DebugSettings(
        telemetry=False,
    ),
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # The flat attributes are set exactly as with flat parameters
    print(f"session_id: {workflow.session_id}")
    print(f"cache_session: {workflow.cache_session}")
    print(f"store_events: {workflow.store_events}")

    workflow.print_response("What is the capital of Japan?")

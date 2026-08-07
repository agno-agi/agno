"""
Configure With Settings
====================================

Configure an Agent with settings dataclasses instead of flat parameters.

Each settings class groups related parameters (session, context, history, ...).
The resulting agent is identical to one built with the flat parameters, and the
flat parameters keep working as before. If a parameter is set both ways, the
settings object wins and a warning is logged if the values differ.
"""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.settings import (
    ContextSettings,
    HistorySettings,
    RetrySettings,
    SessionSettings,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    name="Settings Agent",
    db=InMemoryDb(),
    session_settings=SessionSettings(
        session_id="settings-demo",
        cache_session=True,
    ),
    context_settings=ContextSettings(
        markdown=True,
        add_datetime_to_context=True,
        timezone_identifier="Etc/UTC",
    ),
    history_settings=HistorySettings(
        add_history_to_context=True,
        num_history_runs=5,
    ),
    retry_settings=RetrySettings(
        retries=2,
        exponential_backoff=True,
    ),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # The flat attributes are set exactly as with flat parameters
    print(f"session_id: {agent.session_id}")
    print(f"markdown: {agent.markdown}")
    print(f"num_history_runs: {agent.num_history_runs}")
    print(f"retries: {agent.retries}")

    agent.print_response("What time is it in UTC right now?")

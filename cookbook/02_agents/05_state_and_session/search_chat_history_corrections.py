"""
Search Chat History: Corrections
=============================

The user states a budget, corrects it a few turns later, and asks for it once both are out of the
history window.

search_chat_history labels each match with its turn, so the agent sees the old value and the
correction in order and answers with the later one.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    # Chaining off, so the model sees only the history window below, as with any provider that keeps
    # no conversation on its side.
    model=OpenAIResponses(id="gpt-5.6-luna", use_previous_response_id=False),
    db=SqliteDb(db_file="tmp/agents.db"),
    add_history_to_context=True,
    num_history_runs=2,
    search_chat_history=True,
    instructions=(
        "Earlier turns: only the last 2 turns of this conversation are in front of you. Older turns are "
        "stored. Before you say you do not know something the person told you, or ask for it again, find "
        "it with search_chat_history. Do not search for what is already in front of you."
    ),
)

SETUP = [
    "I'm leading our billing migration to the new ledger service. The load-test budget is 4,200 dollars.",
    "Give me one tip for a rollback runbook, in one sentence.",
    "Correction: finance approved more, the load-test budget is now 6,000 dollars.",
    "Give me one tip for monitoring a cutover, in one sentence.",
    "Give me one tip for a customer maintenance notice, in one sentence.",
]

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = f"search-chat-history-corrections-{uuid4().hex[:8]}"
    for message in SETUP:
        agent.run(message, session_id=session_id)
    print(f"{len(SETUP)} turns stored, only the last 2 are in the history window.")

    response = agent.run("What's our load-test budget?", session_id=session_id)
    for tool in response.tools or []:
        print(f"tool: {tool.tool_name}({tool.tool_args})")
        if tool.tool_name == "search_chat_history":
            print(tool.result)
    print(response.content)

"""
Search Chat History
=============================

An agent that only sees its last two turns finds something said earlier with search_chat_history.

`search_chat_history=True` gives the agent the `search_chat_history` tool. It matches literal text
("|" between alternatives) in the user messages and replies of the current session, and labels each
match with its turn, e.g. `[turn 1 user] ...`. `read_chat_history=True` is a separate flag that adds
`get_chat_history`, which returns whole turns instead.
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
        "Only your last two turns are in front of you; older turns are stored. Before you say you do "
        "not know something the user told you, find it with search_chat_history."
    ),
)

TURNS = [
    "Our staging database is called lumen-stage-7. Keep that in mind.",
    "Give me one tip for naming feature branches, in one sentence.",
    "Give me one tip for writing commit messages, in one sentence.",
    "Give me one tip for code review, in one sentence.",
    "What is our staging database called?",
]

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = f"search-chat-history-{uuid4().hex[:8]}"
    for turn, message in enumerate(TURNS, start=1):
        response = agent.run(message, session_id=session_id)
        print(f"--- turn {turn}: {message}")
        for tool in response.tools or []:
            print(f"tool: {tool.tool_name}({tool.tool_args})")
            if tool.tool_name == "search_chat_history":
                print(tool.result)
        print(response.content)

"""
Compaction on AgentOS
=====================

Serve an agent whose context is compacted as the conversation grows, and watch it
happen from the chat UI.

Compaction folds older turns into a summary once the conversation crosses a
threshold, keeping recent turns verbatim. The stored transcript is never
rewritten - only what is sent to the model gets shorter - so the session still
holds every message.

Two events stream to the UI while it runs:
  CompactionStarted    - a fold has begun
  CompactionCompleted  - messages_compacted, tokens_before, tokens_after

Agno OS renders these in the Behind the Scenes panel of a chat, so a long
conversation shows "Context compacted - 6 messages folded, 17.8k -> 5.5k tokens"
rather than silently losing turns.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/21_compaction/compaction_os.py
Try: open the chat UI, then ask several long questions in one session
"""

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db = PostgresDb(
    id="compaction-db", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# The defaults (fold at 20 runs, keep the last 5) suit a long-lived session.
# These are lowered so a handful of turns in the UI is enough to see a fold.
research_agent = Agent(
    id="compaction-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    add_history_to_context=True,
    # Compaction manages the window, so let history run long rather than
    # capping it at the default three runs.
    num_history_runs=100,
    compaction=Compaction(
        # A cheaper model is enough to write the summary.
        model=OpenAIResponses(id="gpt-5.4"),
        compact_at_runs=4,
        keep_last_runs=2,
        searchable=True,
    ),
    markdown=True,
    instructions=[
        "Answer thoroughly and at length - long answers make the context grow,",
        "which is what this example is demonstrating.",
    ],
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="compaction-os",
    description="An AgentOS showing conversation compaction in the chat UI",
    db=db,
    agents=[research_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="compaction_os:app", reload=True)

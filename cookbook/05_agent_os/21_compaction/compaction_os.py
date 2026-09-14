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

Compaction also folds on demand, without waiting for the threshold:

    POST /agents/{agent_id}/sessions/{session_id}/compact

See rest_api_compaction.py in this folder for that flow end to end.

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
# The default (fold at 150k tokens, keep the last 5 runs) suits a long-lived
# session. These are lowered so a handful of turns in the UI is enough to see a fold.
research_agent = Agent(
    id="compaction-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    add_history_to_context=True,
    compaction=Compaction(
        # A cheaper model is enough to write the summary.
        model=OpenAIResponses(id="gpt-5.4"),
        # Low enough that a chat session in the UI trips it, but above what a single
        # turn of this agent costs: it is instructed to answer at length, and one
        # question-plus-answer runs to ~10k tokens. A threshold under that is crossed
        # on turn one and re-evaluates every turn, mostly to decline.
        compact_at_tokens=25_000,
        # A fold has to be at least min_fold_ratio (2x) the tail it keeps, or it cannot
        # pay for the summary. A 1-turn tail reaches that after a few turns; a larger
        # one needs proportionally more conversation in front of it first.
        keep_last_runs=1,
        searchable=True,
    ),
    markdown=True,
    instructions=[
        "Answer thoroughly and at length - long answers make the context grow,",
        "which is what this example is demonstrating.",
    ],
)

# A second agent with the automatic trigger switched off, so folds happen only when
# something asks for one. rest_api_compaction.py drives this agent: with a threshold
# in play, the server would usually fold first and a manual call would just report
# work it did not do.
manual_agent = Agent(
    id="manual-compaction-agent",
    name="Manual Compaction Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    add_history_to_context=True,
    compaction=Compaction(
        model=OpenAIResponses(id="gpt-5.4"),
        # No automatic trigger: this session folds only via POST .../compact.
        compact_at_tokens=None,
        keep_last_runs=1,
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
    agents=[research_agent, manual_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="compaction_os:app", reload=True)

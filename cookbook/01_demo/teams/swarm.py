"""
Swarm Team — same question, multiple models in parallel
========================================================

Broadcast-mode team. Two web-search agents — one on OpenAI gpt-5.5,
one on Anthropic claude-opus-4-7 — answer the same question.
The leader synthesizes both views and calls out where they agree or disagree.

Use case: "assemble a bunch of agents on a common problem,
preferably mixing OpenAI and Anthropic". Different models often
catch different angles; the leader's job is to reconcile.

Both members share the same `web_provider` instance, so the Parallel MCP
session is opened once and closed once at AgentOS shutdown (see `run.py` lifespan).
"""

from agents.web_search import web_provider
from agno.agent import Agent
from agno.team import Team
from agno.team.mode import TeamMode
from db import get_db
from settings import anthropic_model, default_model

_MEMBER_INSTRUCTIONS = """\
Answer the question using current information from the web.

Call query_web for any non-trivial factual claim. Cite the URLs you
used as plain links. Prefer recent, authoritative sources. If the
search returns nothing useful, say so plainly rather than guessing.
"""


# Member 1 — OpenAI
web_search_openai = Agent(
    id="web-search-openai",
    name="WebSearch (OpenAI)",
    role="Answer the question using OpenAI gpt-5.5.",
    model=default_model(),
    db=get_db(),
    tools=web_provider.get_tools(),
    instructions=_MEMBER_INSTRUCTIONS + "\n\n" + web_provider.instructions(),
    markdown=True,
)

# Member 2 — Anthropic
web_search_anthropic = Agent(
    id="web-search-anthropic",
    name="WebSearch (Anthropic)",
    role="Answer the question using Anthropic claude-opus-4-7.",
    model=anthropic_model(),
    db=get_db(),
    tools=web_provider.get_tools(),
    instructions=_MEMBER_INSTRUCTIONS + "\n\n" + web_provider.instructions(),
    markdown=True,
)


SWARM_INSTRUCTIONS = """\
You lead a two-model swarm: one OpenAI agent and one Anthropic
agent, both answering the same question with web access.

Workflow:
1. Broadcast the user's question to both members.
2. Read both responses.
3. Synthesize a single unified answer:
   - Lead with the answer both models agree on.
   - Call out disagreements explicitly with a "Disagreement:" line
     and a one-sentence reason for each side.
   - Merge citations — keep every URL either member used.
4. End with a one-line "Confidence: high | medium | low" judged on
   whether the models converge.
"""


swarm = Team(
    id="swarm",
    name="Swarm",
    mode=TeamMode.broadcast,
    model=default_model(),
    db=get_db(),
    members=[web_search_openai, web_search_anthropic],
    instructions=SWARM_INSTRUCTIONS,
    show_members_responses=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

"""
Typed Parallel Delegation
=========================
The leader fans one question out to several members at once and gets typed JSON back.

- enable_member_response_schema=True lets the leader pass a JSON Schema with each
  delegation, so every member answers with the same fields and the results can be
  compared and ranked.
- max_concurrent_delegations=2 caps how many members run at the same time, which
  keeps a wide fan-out under provider rate limits.

Delegations the leader makes in one turn run in parallel in async runs.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team.mode import TeamMode
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

python_expert = Agent(
    name="Python Expert",
    role="Assesses programming languages from a Python developer's point of view",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)

rust_expert = Agent(
    name="Rust Expert",
    role="Assesses programming languages from a Rust developer's point of view",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)

go_expert = Agent(
    name="Go Expert",
    role="Assesses programming languages from a Go developer's point of view",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="Language Review Panel",
    mode=TeamMode.coordinate,
    model=OpenAIResponses(id="gpt-5.6-luna"),
    members=[python_expert, rust_expert, go_expert],
    enable_member_response_schema=True,
    max_concurrent_delegations=2,
    instructions=[
        "Ask every expert the same question in the same turn.",
        "Give each delegation a response_schema with a 'language' string, a 'score' integer "
        "from 1 to 10 and a one-sentence 'reason', then rank the answers by score.",
    ],
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(
        team.aprint_response(
            "How well suited is your language for writing a high-throughput HTTP API? "
            "Score it and rank the three languages.",
            stream=True,
        )
    )

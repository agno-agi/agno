"""
Gemini Interactions - Antigravity environment configuration
============================================================

Two non-default ways to control the Antigravity sandbox:

  1. Reuse an existing environment by id (faster startup, persists state
     across runs).
  2. Pass a full EnvironmentConfig dict to declare sources, network rules,
     or other sandbox knobs.

Use a reused environment when the agent needs to build on prior work in the
same sandbox (e.g. an iterative project). Use a custom EnvironmentConfig
when you need a specific source repo, package set, or network policy.
"""

from agno.agent import Agent
from agno.models.google import GeminiInteractions

# ---------------------------------------------------------------------------
# Option 1: Reuse an existing environment by id
# ---------------------------------------------------------------------------
# Replace "env_xxxxxxxx" with the id of a sandbox the API has already
# provisioned for you (e.g. returned from a prior interaction).

agent_reuse = Agent(
    model=GeminiInteractions(
        agent="antigravity-preview-05-2026",
        environment="env_xxxxxxxx",
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Option 2: Full EnvironmentConfig (custom sources / network rules)
# ---------------------------------------------------------------------------
# The dict shape mirrors the API's EnvironmentConfig. Only the keys you set
# are sent; the API applies sensible defaults for the rest.

agent_custom = Agent(
    model=GeminiInteractions(
        agent="antigravity-preview-05-2026",
        environment={
            "type": "remote",
            "sources": [
                {"type": "git", "url": "https://github.com/agno-agi/agno"},
            ],
            "network": {"allow_internet_access": True},
        },
    ),
    markdown=True,
)

if __name__ == "__main__":
    agent_reuse.print_response(
        "Continue the project we started last time and ship the next "
        "iteration of the report."
    )

    agent_custom.print_response(
        "Skim the repo we cloned, summarize the module layout, and save "
        "the summary to STRUCTURE.md inside the sandbox."
    )

"""
Nimble Agent Tools
=============================

Demonstrates NimbleAgentTools: Nimble's Web Search Agent (Agent API V2) run
lifecycle exposed as separate start, status, and result tools.

Runs are asynchronous, so the agent drives the loop itself: it starts a run,
polls the status until the run is terminal, then fetches the grounded result
with its sources, confidence, and cited claims.

Prerequisites:
- Create a Nimble account and get an API key
- Install the SDK: pip install "agno[nimble]"
- Set the API key as an environment variable:
    export NIMBLE_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.tools.nimble_agent import NimbleAgentTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: no agent id needed. Nimble provisions an agent for the run and
# returns its id, which the toolkit reuses for the status and result calls.
agent = Agent(tools=[NimbleAgentTools()], markdown=True)

# Example 2: run against an agent you already own, with discovery turned off.
pinned_agent = Agent(
    tools=[NimbleAgentTools(agent_id="wsa_your_agent_id", enable_discovery=False)],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Research: start a run, poll it, then return the answer with its sources.
    agent.print_response(
        "Start a Nimble research run for the current stable Python release. "
        "Prioritize official python.org sources, poll the run until it completes, "
        "then give me the answer with its sources and confidence."
    )

    # Enrichment: the same lifecycle, with a JSON output contract so the result
    # comes back as structured, citable fields instead of prose.
    agent.print_response(
        "Start a Nimble enrichment run for the company Nimble (nimbleway.com) "
        "with output_schema {'type': 'object', 'properties': "
        "{'headquarters': {'type': 'string'}, 'founded_year': {'type': 'integer'}}}. "
        "Poll until it completes, then report the fields and where each came from."
    )

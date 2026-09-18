"""
OrcaReplay Integration
======================

Demonstrates recording an Agno agent from outside the process, then replaying that run
offline — no provider contacted, no key, no token spend.

Unlike the other examples here, there is nothing to initialize: OrcaReplay does not
instrument the agent. It wraps the process you launch and moves the base-URL variable for
that child only, so this file is an ordinary Agno script. What changes is how you run it.

    npm i -g orcareplay
    orca record generic-openai -- python cookbook/observability/orcareplay_op.py
    orca replay last

Measured on agno 3.0.9 with openai 3.14.1: the run above replayed at
`reused=1/1 exact=1 divergences=0 unmatched=0` with the origin unreachable.

Note that `OpenAIChat` picks up `OPENAI_BASE_URL` and ignores `OPENAI_API_BASE`; the
`generic-openai` adapter sets both, so nothing here depends on which one you use.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Nothing to set up. Recording happens outside the process — see the module docstring.


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), markdown=False)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("In one sentence: what does a record-and-replay tool do?")

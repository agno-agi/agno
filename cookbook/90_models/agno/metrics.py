"""
Agno Gateway - metrics
======================

The gateway returns OpenAI-style usage, so per-message and aggregated metrics work as
usual. When the gateway reports a ``cost`` field it is surfaced on the message metrics.

Requires:
- AGNO_API_KEY  (or a provider key for BYOK, e.g. OPENAI_API_KEY for "openai/...")
"""

from agno.agent import Agent, RunOutput
from agno.models.agno import Agno
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Agno(id="openai/gpt-5.4"),
    markdown=True,
)

run_output: RunOutput = agent.run("Share a 2 sentence horror story")
print(run_output.content)

# Per-message metrics
if run_output.messages:
    for message in run_output.messages:
        if message.role == "assistant":
            print("---" * 5, "Message Metrics", "---" * 5)
            pprint(message.metrics)

# Aggregated run metrics
print("---" * 5, "Collected Metrics", "---" * 5)
pprint(run_output.metrics)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass

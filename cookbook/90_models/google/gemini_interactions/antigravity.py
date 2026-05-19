"""
Gemini Interactions - Antigravity agent
========================================

Run the Antigravity managed agent through the Gemini Interactions API.

Antigravity is a general-purpose autonomous agent (Gemini 3.5 Flash) that can
plan, run code, browse the web, and produce artifacts (PDFs, HTML, slides)
inside a managed sandbox. The `environment` parameter selects the sandbox:

  - "remote"        -> fresh remote Linux sandbox (default for new sessions)
  - "env_<id>"      -> reuse a previously provisioned environment
  - {dict}          -> full EnvironmentConfig (sources, network, etc.)

Unlike Deep Research, Antigravity runs in the foreground (no background mode);
the model still forces `store=True` so the interaction is retrievable.
"""

from agno.agent import Agent
from agno.models.google import GeminiInteractions

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=GeminiInteractions(
        agent="antigravity-preview-05-2026",
        environment="remote",
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Plot the growth of global solar energy generation over the last "
        "decade and produce a short HTML slide deck summarizing the trend."
    )

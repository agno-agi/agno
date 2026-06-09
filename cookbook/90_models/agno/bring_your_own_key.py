"""
Agno Gateway - bring your own key (BYOK)
========================================

The Agno gateway works two ways, both routed through the gateway:

1. Managed: set ``AGNO_API_KEY`` (billed through your Agno account).
2. BYOK: bring your own provider key. With ``AGNO_API_KEY`` unset, the class uses the
   provider key for the model id prefix (e.g. ``OPENAI_API_KEY`` for ``openai/...``),
   or pass ``api_key=...`` explicitly to force BYOK.

Key resolution order: explicit ``api_key`` > ``AGNO_API_KEY`` > the provider key for
the id prefix.

Requires one of:
- AGNO_API_KEY              (managed)
- OPENAI_API_KEY / ...      (BYOK, matching the model id prefix)
"""

from agno.agent import Agent
from agno.models.agno import Agno

# ---------------------------------------------------------------------------
# BYOK by environment: with AGNO_API_KEY unset, OPENAI_API_KEY is used for "openai/..."
# ---------------------------------------------------------------------------

agent = Agent(
    model=Agno(id="openai/gpt-5.4"),
    markdown=True,
)

# Or pass your provider key explicitly (forces BYOK even if AGNO_API_KEY is set):
#
#   agent = Agent(model=Agno(id="openai/gpt-5.4", api_key="sk-..."), markdown=True)

if __name__ == "__main__":
    agent.print_response("Share a 2 sentence horror story")

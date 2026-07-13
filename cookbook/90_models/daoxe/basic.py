"""
DaoXE Basic
===========

OpenAI-compatible multi-model multi-protocol gateway example.

DaoXE exposes Chat Completions at https://daoxe.com/v1. Use an API key from the
DaoXE dashboard and an exact model ID from your account catalog (GET /v1/models).
Do not hardcode a public model price list.

Docs: https://github.com/seven7763/DaoXE-AI
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

model_id = os.environ.get("DAOXE_MODEL", "YOUR_DAOXE_MODEL_ID")
api_key = os.environ.get("DAOXE_API_KEY")
if not api_key:
    raise SystemExit("Set DAOXE_API_KEY to your DaoXE dashboard API key.")

agent = Agent(
    model=OpenAIChat(
        id=model_id,
        api_key=api_key,
        base_url="https://daoxe.com/v1",
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Share a 2 sentence practical tip about API gateways")

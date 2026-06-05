"""
Agno agent with Entroly cost optimization.

Run the Entroly proxy first:
    pip install entroly
    entroly proxy

Then run this example:
    python cookbook/92_integrations/entroly/entroly_proxy_agent.py

Entroly compresses context by 70-95% and aligns provider cache prefixes
for additional discounts (Anthropic 90%, OpenAI 50%).
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# Point OpenAI-compatible requests at the Entroly local proxy.
# Entroly transparently compresses context and forwards to the real provider.
os.environ["OPENAI_BASE_URL"] = "http://localhost:9377/v1"

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    description="You are a helpful coding assistant.",
    instructions=[
        "Analyze code and provide clear explanations.",
        "Suggest improvements when appropriate.",
    ],
    markdown=True,
)

agent.print_response(
    "Explain how a Python decorator works and give a practical example.",
    stream=True,
)

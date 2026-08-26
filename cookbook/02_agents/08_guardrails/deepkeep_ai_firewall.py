"""
DeepKeep AI Firewall Guardrails
===============================

This example shows how to use DeepKeep AI Firewall as custom guardrails for
Agno Agents. DeepKeep runs before user input reaches the model and after model
output is generated.

Requirements:
- pip install agno-deepkeep
- DEEPKEEP_API_KEY and DEEPKEEP_BASE_URL set

Set credentials before running:

    export DEEPKEEP_API_KEY="dk_..."
    export DEEPKEEP_BASE_URL="https://api.example.deepkeep.ai"

Usage:
    python cookbook/02_agents/08_guardrails/deepkeep_ai_firewall.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno_deepkeep import DeepKeepGuardrail


agent = Agent(
    name="DeepKeep Protected Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions="Answer user questions safely and concisely.",
    pre_hooks=[
        DeepKeepGuardrail(
            pre_model="input-firewall-id",
        )
    ],
    post_hooks=[
        DeepKeepGuardrail(
            post_model="output-firewall-id",
        )
    ],
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response("Explain how to store API keys securely.")

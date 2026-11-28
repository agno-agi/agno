"""Run Hermes through Agno from an activated Hermes source environment."""

from os import getenv

from agno.agents.hermes import HermesAgent

agent = HermesAgent(
    name="Hermes",
    model=getenv("HERMES_MODEL"),
    enabled_toolsets=[],
    skip_context_files=True,
    max_iterations=10,
)

if __name__ == "__main__":
    agent.print_response("Explain what an AI agent is in two sentences.", stream=True)

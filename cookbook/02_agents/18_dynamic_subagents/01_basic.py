"""
Dynamic Subagents — Basic Usage
================================

Demonstrates the simplest dynamic subagent setup.
The orchestrator LLM decides on its own when to spawn a subagent.
Spawned agents run in a completely isolated context: their tool outputs
never appear in the orchestrator's message history.

Key concepts:
- enable_dynamic_subagents=True adds the spawn_agent tool automatically
- The LLM chooses when and what to spawn — no extra developer code needed
- Context isolation is architectural, not compressive

Prompts to try:
- "Write a short poem about Python, then separately explain its history."
- "Give me a haiku about the ocean and a limerick about coffee."
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="orchestrator",
    model=OpenAIResponses(id="gpt-5.4"),
    enable_dynamic_subagents=True,
    instructions=(
        "You are a helpful assistant. When a task benefits from specialist focus "
        "or would return large intermediate data, use spawn_agent to delegate it."
    ),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Write a short poem about the Python programming language, "
        "then separately explain why Python is popular for data science.",
        stream=True,
    )

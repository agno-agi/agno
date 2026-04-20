"""
Dynamic Subagents — Tool Delegation
=====================================

Demonstrates delegating parent tools to spawned subagents.
The orchestrator has web-search tools. When it spawns a subagent, it
can pass those tools along. The subagent's tool outputs stay isolated;
the orchestrator only receives the final summary.

Key concepts:
- subagent_template defines the base agent cloned at spawn time
- allowed_tools whitelists which tool NAMES may appear on subagents. It
  applies to both template toolkits and parent tools — toolkits contribute
  only the Function objects whose names appear in the whitelist.
- allow_tool_selection lets the LLM pick the right tools per task

Prompts to try:
- "Research quantum computing advances and separately find recent AI safety news."
- "Search for Python 3.13 features and also look up Rust 2024 edition highlights."
"""

from agno.agent import Agent, SubAgentConfig
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Create Subagent Template
# ---------------------------------------------------------------------------
# The template is deep-copied at each spawn. The LLM sets role, instructions,
# and task dynamically; the template provides the base model and tools.
subagent_template = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="research_orchestrator",
    model=OpenAIChat(id="gpt-4o"),
    enable_dynamic_subagents=True,
    subagent_template=subagent_template,
    subagent_config=SubAgentConfig(
        allow_tool_selection=True,
        allowed_tools=["duckduckgo_search", "duckduckgo_news"],
        max_concurrent=2,
    ),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Research the latest developments in quantum computing and "
        "separately look up recent AI safety news. Give me a combined summary.",
        stream=True,
    )

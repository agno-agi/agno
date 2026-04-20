"""
Dynamic Subagents — Parallel Spawning
=======================================

Demonstrates concurrent subagent execution.
The LLM can emit multiple spawn_agent calls in a single turn.
All async subagents execute concurrently, bounded by max_concurrent.

Key concepts:
- aprint_response / arun enables the async spawn path
- max_concurrent caps how many subagents run simultaneously
- Use asyncio.gather-style orchestration instructions to prompt parallelism

Prompts to try:
- "In parallel: research Python 3.13 features, Rust 2024 edition, and WebAssembly news."
- "Simultaneously look up: recent SpaceX launches, latest NASA Mars mission updates."
"""

import asyncio

from agno.agent import Agent, SubAgentConfig
from agno.models.openai import OpenAIResponses
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Create Subagent Template
# ---------------------------------------------------------------------------
subagent_template = Agent(
    model=OpenAIResponses(id="gpt-5.4-mini"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="parallel_orchestrator",
    model=OpenAIResponses(id="gpt-5.4"),
    enable_dynamic_subagents=True,
    subagent_template=subagent_template,
    subagent_config=SubAgentConfig(
        allow_tool_selection=True,
        max_concurrent=3,
    ),
    instructions=(
        "When asked for multiple independent pieces of research, spawn "
        "all subagents in parallel by emitting multiple spawn_agent calls "
        "in a single response."
    ),
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def main() -> None:
    await agent.aprint_response(
        "In parallel: (1) research Python 3.13 new features, "
        "(2) look up the latest Rust release notes, "
        "(3) find recent news about WebAssembly.",
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())

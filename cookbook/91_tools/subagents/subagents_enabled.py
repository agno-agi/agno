"""
Enable Subagents with a Flag
============================

The one-liner: Agent(enable_subagents=True). The agent gets a default
SubagentsConfig, so subagents inherit the agent's model (offered as the single
"default" option) and all of its tools - no config object needed. Pass
subagents_config=SubagentsConfig(...) instead when you want to control the
model options or restrict the allowed tools.

The agent gets one tool, spawn_agent(task), and parallelizes by calling it
multiple times in the same response. Subagents run in-process inside the
parent's run and nothing about them is persisted.

Run: .venvs/demo/bin/python cookbook/91_tools/subagents/subagents_enabled.py
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.websearch import WebSearchTools

agent = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[WebSearchTools()],
    enable_subagents=True,
    instructions=(
        "Split independent research into one spawn_agent call per topic in a "
        "single response. Ask each subagent for a short sourced summary, then "
        "synthesize the findings yourself."
    ),
    markdown=True,
)

if __name__ == "__main__":
    asyncio.run(
        agent.aprint_response(
            "Research two topics in parallel: the largest desert on Earth, and "
            "the most recently discovered element. One short sourced paragraph "
            "each.",
            stream=True,
        )
    )

"""
Subagents with Defaults
=======================

The minimal setup: Agent(subagents_config=SubagentsConfig()). With no options set,
subagents inherit the parent's model (offered as the single "default" option)
and all of the parent's tools.

The agent gets one tool, spawn_agent(task), and parallelizes by calling it
multiple times in the same response. Subagents run in-process inside the
parent's run: their events stream nested into the parent's output and the tool
result is each subagent's answer. Nothing about them is persisted.

Run: .venvs/demo/bin/python cookbook/91_tools/subagents/subagents_defaults.py
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.subagent import SubagentsConfig
from agno.tools.websearch import WebSearchTools

agent = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[WebSearchTools()],
    subagents_config=SubagentsConfig(),
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
            "Research two topics in parallel: the tallest building currently "
            "under construction, and the most recent Mars rover discovery. "
            "One short sourced paragraph each.",
            stream=True,
        )
    )

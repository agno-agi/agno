"""
Subagents with a Single Model
=============================

Pass SubagentsConfig(model=...) and every subagent runs on that model - no
options dict needed. The classic split: the orchestrator thinks on the big
model while subagents burn through the busywork on a cheaper, faster one.

The spawn_agent tool then offers just that one option, so the model never has
to pick - it only writes the task briefs.

Run: .venvs/demo/bin/python cookbook/91_tools/subagents/subagents_single_model.py
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.subagent import SubagentsConfig
from agno.tools.websearch import WebSearchTools

agent = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.6-terra"),
    tools=[WebSearchTools()],
    subagents_config=SubagentsConfig(model=OpenAIResponses(id="gpt-5.6-luna")),
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
            "Research two topics in parallel: the deepest point of the ocean, "
            "and the fastest train currently in service. One short sourced "
            "paragraph each.",
            stream=True,
        )
    )

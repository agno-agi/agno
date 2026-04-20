"""
Dynamic Subagents — Team Integration
======================================

Demonstrates enabling dynamic subagents on a Team.
When the team leader spawns a subagent, it is linked to the team via
team_id so its runs appear in the same session for observability.

Key concepts:
- Team accepts the same enable_dynamic_subagents / subagent_template / subagent_config fields as Agent
- Spawned subagents carry team_id in their metadata
- Subagents complement registered team members — both can be used in the same run

Prompts to try:
- "Research Python history and write a 200-word blog summary."
- "Find the latest news on large language models and draft a short newsletter blurb."
"""

from agno.agent import Agent, SubAgentConfig
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Create Team Members
# ---------------------------------------------------------------------------
researcher = Agent(
    name="researcher",
    model=OpenAIResponses(id="gpt-5.4-mini"),
    tools=[DuckDuckGoTools()],
    instructions="Search the web and return factual results.",
)

writer = Agent(
    name="writer",
    model=OpenAIResponses(id="gpt-5.4-mini"),
    instructions="Write clear, well-structured prose.",
)

# ---------------------------------------------------------------------------
# Create Subagent Template
# ---------------------------------------------------------------------------
subagent_template = Agent(
    model=OpenAIResponses(id="gpt-5.4-mini"),
    tools=[DuckDuckGoTools()],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="content_team",
    members=[researcher, writer],
    model=OpenAIResponses(id="gpt-5.4"),
    enable_dynamic_subagents=True,
    subagent_template=subagent_template,
    subagent_config=SubAgentConfig(
        context_heavy_tools=["duckduckgo_search"],
        max_concurrent=2,
    ),
    instructions=(
        "Coordinate your team members. For large data-fetching tasks "
        "that would flood the context, use spawn_agent to isolate them."
    ),
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    team.print_response(
        "Research the history of the Python programming language and write "
        "a 200-word summary suitable for a blog post.",
        stream=True,
    )

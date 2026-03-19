"""
Team Fallback Models — Error-Specific
=======================================

Use FallbackConfig for error-specific fallback routing on Teams.

- models: tried on any error from the primary model.
- rate_limit_models: tried specifically on rate-limit (429) errors.
- context_window_models: tried on context-window-exceeded errors.
"""

from agno.agent import Agent
from agno.fallback import FallbackConfig
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.team import Team

researcher = Agent(
    name="Researcher",
    role="You research topics and provide detailed findings.",
    model=OpenAIChat(id="gpt-4o-mini"),
)

writer = Agent(
    name="Writer",
    role="You write clear, concise summaries from research findings.",
    model=OpenAIChat(id="gpt-4o-mini"),
)

team = Team(
    name="Research Team",
    model=OpenAIChat(id="gpt-4o"),
    fallback_config=FallbackConfig(
        rate_limit_models=[
            OpenAIChat(id="gpt-4o-mini"),
            Claude(id="claude-sonnet-4-20250514"),
        ],
        context_window_models=[
            Claude(id="claude-sonnet-4-20250514"),
        ],
        models=[
            Claude(id="claude-sonnet-4-20250514"),
        ],
    ),
    members=[researcher, writer],
    instructions=[
        "Coordinate with the researcher and writer to answer the user question.",
    ],
    markdown=True,
    show_members_responses=True,
)

if __name__ == "__main__":
    team.print_response("What are the benefits of sleep?", stream=True)

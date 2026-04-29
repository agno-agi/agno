"""
Team Fallback Models — Basic
=============================

When the team leader's primary model fails (after exhausting retries),
fallback models are tried in order until one succeeds.
"""

from agno.agent import Agent
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
    model=OpenAIChat(id="gpt-4o", base_url="http://localhost:1/v1", retries=0),
    fallback_models=[Claude(id="claude-sonnet-4-20250514")],
    members=[researcher, writer],
    instructions=[
        "Coordinate with the researcher and writer to answer the user question.",
    ],
    markdown=True,
    show_members_responses=True,
)

if __name__ == "__main__":
    team.print_response("What are the benefits of sleep?", stream=True)

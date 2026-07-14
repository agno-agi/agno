"""
Coordinate Mode with Tools

Demonstrates coordination where member agents have specialized tools.
The team leader delegates to the right member based on what tools are needed.

"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team.mode import TeamMode
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

hn_researcher = Agent(
    name="HackerNews Researcher",
    role="Searches and summarizes stories from Hacker News",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[HackerNewsTools()],
    instructions=[
        "You search Hacker News for relevant stories.",
        "Provide titles, scores, and brief summaries of what you find.",
    ],
)

web_searcher = Agent(
    name="Web Searcher",
    role="Searches the web for general information",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[DuckDuckGoTools()],
    instructions=[
        "You search the web for relevant information.",
        "Provide concise summaries with key facts.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="News Research Team",
    mode=TeamMode.coordinate,
    model=OpenAIResponses(id="gpt-5.2"),
    members=[hn_researcher, web_searcher],
    instructions=[
        "You lead a news research team.",
        "For tech/startup topics, use the HackerNews Researcher.",
        "For broader topics, use the Web Searcher.",
        "You can use both when a comprehensive view is needed.",
        "Synthesize findings into a clear summary.",
    ],
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    team.print_response(
        "What are the latest developments in AI agents? "
        "Check both Hacker News and the web.",
        stream=True,
    )

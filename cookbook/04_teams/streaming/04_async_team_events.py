"""
This example demonstrates how to handle and monitor team events asynchronously.

Shows how to capture and respond to various events during async team execution,
including tool calls, run states, and content generation events.
"""

import asyncio
from uuid import uuid4

from agno.agent import RunEvent
from agno.agent.agent import Agent
from agno.models.anthropic.claude import Claude
from agno.models.openai import OpenAIChat
from agno.team.team import Team, TeamRunEvent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools

# Hacker News search agent
hacker_news_agent = Agent(
    id="hacker-news-agent",
    name="Hacker News Agent",
    role="Search Hacker News for information",
    tools=[HackerNewsTools()],
    instructions=[
        "Find articles about the company in the Hacker News",
    ],
)

# Web search agent
website_agent = Agent(
    id="website-agent",
    name="Website Agent",
    role="Search the website for information",
    model=OpenAIChat(id="o3-mini"),
    tools=[DuckDuckGoTools()],
    instructions=[
        "Search the website for information",
    ],
)

# Generate unique IDs
user_id = str(uuid4())
team_id = str(uuid4())

# Create team with event monitoring
company_info_team = Team(
    name="Company Info Team",
    id=team_id,
    model=Claude(id="claude-3-7-sonnet-latest"),
    members=[
        hacker_news_agent,
        website_agent,
    ],
    markdown=True,
    instructions=[
        "You are a team that finds information about a company.",
        "First search the web and Hacker News for information about the company.",
        "If you can find the company's website URL, then scrape the homepage and the about page.",
    ],
    show_members_responses=True,
)


async def run_team_with_events(prompt: str):
    """
    Run the team and capture all events for monitoring and debugging.

    This function demonstrates how to handle different types of events:
    - Team-level events (run start/completion, tool calls)
    - Member-level events (agent tool calls)
    - Content generation events
    """
    content_started = False

    async for run_response_event in company_info_team.arun(
        prompt,
        stream=True,
        stream_events=True,
    ):
        # Handle team-level events
        if run_response_event.event in [
            TeamRunEvent.run_started,
            TeamRunEvent.run_completed,
        ]:
            print(f"\n🎯 TEAM EVENT: {run_response_event.event}")

        # Handle team tool call events
        if run_response_event.event in [TeamRunEvent.tool_call_started]:
            print(f"\n🔧 TEAM TOOL STARTED: {run_response_event.tool.tool_name}")
            print(f"   Args: {run_response_event.tool.tool_args}")

        if run_response_event.event in [TeamRunEvent.tool_call_completed]:
            print(f"\n✅ TEAM TOOL COMPLETED: {run_response_event.tool.tool_name}")
            print(f"   Result: {run_response_event.tool.result}")

        # Handle member-level events
        if run_response_event.event in [RunEvent.tool_call_started]:
            print(f"\n🤖 MEMBER TOOL STARTED: {run_response_event.agent_id}")
            print(f"   Tool: {run_response_event.tool.tool_name}")
            print(f"   Args: {run_response_event.tool.tool_args}")

        if run_response_event.event in [RunEvent.tool_call_completed]:
            print(f"\n✅ MEMBER TOOL COMPLETED: {run_response_event.agent_id}")
            print(f"   Tool: {run_response_event.tool.tool_name}")
            print(
                f"   Result: {run_response_event.tool.result[:100]}..."
            )  # Truncate for readability

        # Handle content generation
        if run_response_event.event in [TeamRunEvent.run_content]:
            if not content_started:
                print("\n📝 CONTENT:")
                content_started = True
            else:
                print(run_response_event.content, end="")


if __name__ == "__main__":
    asyncio.run(
        run_team_with_events(
            "Write me a full report on everything you can find about Agno, the company building AI agent infrastructure.",
        )
    )

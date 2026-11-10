"""
Concurrent Member Agents
=============================

Demonstrates concurrent delegation to team members with streamed member events.
"""

import asyncio
import time

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
hackernews_agent = Agent(
    name="Hackernews Agent",
    role="Handle hackernews requests",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[HackerNewsTools()],
    instructions="Always include sources",
    stream=True,
    stream_events=True,
)

news_agent = Agent(
    name="News Agent",
    role="Handle news requests and current events analysis",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[WebSearchTools()],
    instructions=[
        "Use tables to display news information and findings.",
        "Clearly state the source and publication date.",
        "Focus on delivering current and relevant news insights.",
    ],
    stream=True,
    stream_events=True,
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
research_team = Team(
    name="Reasoning Research Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[hackernews_agent, news_agent],
    instructions=[
        "Collaborate to provide comprehensive research and news insights",
        "Research latest world news and hackernews posts",
        "Use tables and charts to display data clearly and professionally",
    ],
    markdown=True,
    show_members_responses=True,
    stream_member_events=True,
)


async def test() -> None:
    print("Starting agent run...")
    start_time = time.time()

    generator = research_team.arun(
        """Research and compare recent developments in AI Agents:
        1. Get latest news about AI Agents from all your sources
        2. Compare and contrast the news from all your sources
        3. Provide a summary of the news from all your sources""",
        stream=True,
        stream_events=True,
    )

    async for event in generator:
        current_time = time.time() - start_time

        if hasattr(event, "event"):
            if "ToolCallStarted" in event.event:
                print(f"[{current_time:.2f}s] {event.event} - {event.tool.tool_name}")
            elif "ToolCallCompleted" in event.event:
                print(f"[{current_time:.2f}s] {event.event} - {event.tool.tool_name}")
            elif "RunStarted" in event.event:
                print(f"[{current_time:.2f}s] {event.event}")

    total_time = time.time() - start_time
    print(f"Total execution time: {total_time:.2f}s")


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(test())

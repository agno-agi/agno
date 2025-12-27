"""
This example shows how a team will delegate to member agents concurrently.

You should see both member agents starting at the same time, but finishing at different times. And you'll see the member events streaming concurrently.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools

hackernews_agent = Agent(
    name="Hackernews Agent",
    role="Handle hackernews requests",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[HackerNewsTools()],
    instructions="Always include sources",
    stream=True,
    stream_events=True,
)

news_agent = Agent(
    name="News Agent",
    role="Handle news requests and current events analysis",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[DuckDuckGoTools()],
    instructions=[
        "Use tables to display news information and findings.",
        "Clearly state the source and publication date.",
        "Focus on delivering current and relevant news insights.",
    ],
    stream=True,
    stream_events=True,
)

research_team = Team(
    name="Reasoning Research Team",
    model=OpenAIChat(id="gpt-4.1"),
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


async def test():
    import time

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


if __name__ == "__main__":
    import asyncio

    asyncio.run(test())

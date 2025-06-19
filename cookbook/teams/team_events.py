import asyncio
from uuid import uuid4

from agno.agent import RunEvent
from agno.agent.agent import Agent
from agno.models.anthropic.claude import Claude
from agno.models.mistral.mistral import MistralChat
from agno.models.openai.chat import OpenAIChat
from agno.team import Team, TeamRunEvent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools

wikipedia_agent = Agent(
    agent_id="hacker-news-agent",
    name="Hacker News Agent",
    role="Search Hacker News for information",
    model=MistralChat(id="mistral-large-latest"),
    tools=[HackerNewsTools()],
    instructions=[
        "Find articles about the company in the Hacker News",
    ],
)

website_agent = Agent(
    agent_id="website-agent",
    name="Website Agent",
    role="Search the website for information",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    instructions=[
        "Search the website for information",
    ],
)

user_id = str(uuid4())
team_id = str(uuid4())

company_info_team = Team(
    name="Company Info Team",
    mode="coordinate",
    team_id=team_id,
    user_id=user_id,
    model=Claude(id="claude-3-7-sonnet-latest"),
    members=[
        wikipedia_agent,
        website_agent,
    ],
    show_tool_calls=True,
    markdown=True,
    instructions=[
        "You are a team that finds information about a company.",
        "First search the web and wikipedia for information about the company.",
        "If you can find the company's website URL, then scrape the homepage and the about page.",
    ],
    show_members_responses=True,
)


async def run_team_with_events(prompt: str):
    content_started = False
    async for run_response_event in await company_info_team.arun(
        prompt,
        stream=True,
        stream_intermediate_steps=True,
    ):
        if run_response_event.event in [
            TeamRunEvent.run_started,
            TeamRunEvent.run_completed,
        ]:
            print(f"\nTEAM EVENT: {run_response_event.event}")

        if run_response_event.event in [TeamRunEvent.tool_call_started]:
            print(f"\nTEAM EVENT: {run_response_event.event}")
            print(f"TOOL CALL: {run_response_event.tool.tool_name}")
            print(f"TOOL CALL ARGS: {run_response_event.tool.tool_args}")

        if run_response_event.event in [TeamRunEvent.tool_call_completed]:
            print(f"\nTEAM EVENT: {run_response_event.event}")
            print(f"TOOL CALL: {run_response_event.tool.tool_name}")
            print(f"TOOL CALL RESULT: {run_response_event.tool.result}")

        # Member events
        if run_response_event.event in [RunEvent.tool_call_started]:
            print(f"\nMEMBER EVENT: {run_response_event.event}")
            print(f"AGENT ID: {run_response_event.agent_id}")
            print(f"TOOL CALL: {run_response_event.tool.tool_name}")
            print(f"TOOL CALL ARGS: {run_response_event.tool.tool_args}")

        if run_response_event.event in [RunEvent.tool_call_completed]:
            print(f"\nMEMBER EVENT: {run_response_event.event}")
            print(f"AGENT ID: {run_response_event.agent_id}")
            print(f"TOOL CALL: {run_response_event.tool.tool_name}")
            print(f"TOOL CALL RESULT: {run_response_event.tool.result}")

        if run_response_event.event in [TeamRunEvent.run_response_content]:
            if not content_started:
                print("CONTENT")
                content_started = True
            else:
                print(run_response_event.content, end="")


if __name__ == "__main__":
    asyncio.run(
        run_team_with_events(
            "Write me a full report on everything you can find about Agno, the company building AI agent infrastructure.",
        )
    )

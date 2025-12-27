import asyncio
from uuid import uuid4

from agno.agent import RunEvent
from agno.agent.agent import Agent
from agno.models.anthropic.claude import Claude

# from agno.models.mistral.mistral import MistralChat
from agno.models.openai.chat import OpenAIChat
from agno.team import Team, TeamRunEvent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools

wikipedia_agent = Agent(
    id="hacker-news-agent",
    name="Hacker News Agent",
    role="Search Hacker News for information",
    # model=MistralChat(id="mistral-large-latest"),
    tools=[HackerNewsTools()],
    instructions=[
        "Find articles about the company in the Hacker News",
    ],
)

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

user_id = str(uuid4())
team_id = str(uuid4())

company_info_team = Team(
    name="Company Info Team",
    id=team_id,
    user_id=user_id,
    model=Claude(id="claude-3-7-sonnet-latest"),
    members=[
        wikipedia_agent,
        website_agent,
    ],
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
    async for run_output_event in company_info_team.arun(
        prompt,
        stream=True,
        stream_events=True,
    ):
        if run_output_event.event in [
            TeamRunEvent.run_started,
            TeamRunEvent.run_completed,
        ]:
            print(f"\nTEAM EVENT: {run_output_event.event}")

        if run_output_event.event in [TeamRunEvent.tool_call_started]:
            print(f"\nTEAM EVENT: {run_output_event.event}")
            print(f"TOOL CALL: {run_output_event.tool.tool_name}")
            print(f"TOOL CALL ARGS: {run_output_event.tool.tool_args}")

        if run_output_event.event in [TeamRunEvent.tool_call_completed]:
            print(f"\nTEAM EVENT: {run_output_event.event}")
            print(f"TOOL CALL: {run_output_event.tool.tool_name}")
            print(f"TOOL CALL RESULT: {run_output_event.tool.result}")

        # Member events
        if run_output_event.event in [RunEvent.tool_call_started]:
            print(f"\nMEMBER EVENT: {run_output_event.event}")
            print(f"AGENT ID: {run_output_event.agent_id}")
            print(f"TOOL CALL: {run_output_event.tool.tool_name}")
            print(f"TOOL CALL ARGS: {run_output_event.tool.tool_args}")

        if run_output_event.event in [RunEvent.tool_call_completed]:
            print(f"\nMEMBER EVENT: {run_output_event.event}")
            print(f"AGENT ID: {run_output_event.agent_id}")
            print(f"TOOL CALL: {run_output_event.tool.tool_name}")
            print(f"TOOL CALL RESULT: {run_output_event.tool.result}")

        if run_output_event.event in [TeamRunEvent.run_content]:
            if not content_started:
                print("CONTENT")
                content_started = True
            else:
                print(run_output_event.content, end="")


if __name__ == "__main__":
    asyncio.run(
        run_team_with_events(
            "Write me a full report on everything you can find about Agno, the company building AI agent infrastructure.",
        )
    )

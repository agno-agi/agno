import asyncio

from agno.agent import RunEvent
from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.team import Team, TeamRunEvent
from agno.tools.yfinance import YFinanceTools

stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a stock.",
    tools=[
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
        )
    ],
)

company_info_agent = Agent(
    name="Company Info Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a stock.",
    tools=[
        YFinanceTools(
            stock_price=False,
            company_info=True,
            company_news=True,
        )
    ],
)

team = Team(
    name="Stock Research Team",
    mode="route",
    model=OpenAIChat("gpt-4o"),
    members=[stock_searcher, company_info_agent],
    markdown=True,
    # If you want to disable the member events, set this to False (default is True)
    # stream_member_events=False
)


async def run_team_with_events(prompt: str):
    content_started = False
    member_content_started = False
    async for run_response_event in await team.arun(
        prompt,
        stream=True,
        stream_intermediate_steps=True,
    ):
        if run_response_event.event in [
            TeamRunEvent.run_started,
            TeamRunEvent.run_completed,
        ]:
            print(f"\nTEAM EVENT: {run_response_event.event}")
        if run_response_event.event in [
            RunEvent.run_started,
            RunEvent.run_completed,
        ]:
            print(f"\nMEMBER RUN EVENT: {run_response_event.event}")

        if run_response_event.event in [TeamRunEvent.tool_call_started]:
            print(f"\nTEAM EVENT: {run_response_event.event}")
            print(f"TEAM TOOL CALL: {run_response_event.tool.tool_name}")
            print(f"TEAM TOOL CALL ARGS: {run_response_event.tool.tool_args}")

        if run_response_event.event in [TeamRunEvent.tool_call_completed]:
            print(f"\nTEAM EVENT: {run_response_event.event}")
            print(f"TEAM TOOL CALL: {run_response_event.tool.tool_name}")
            print(f"TEAM TOOL CALL RESULT: {run_response_event.tool.result}")

        # Member events
        if run_response_event.event in [RunEvent.tool_call_started]:
            print(f"\nMEMBER EVENT: {run_response_event.event}")
            print(f"TOOL CALL: {run_response_event.tool.tool_name}")
            print(f"TOOL CALL ARGS: {run_response_event.tool.tool_args}")

        if run_response_event.event in [RunEvent.tool_call_completed]:
            print(f"\nMEMBER EVENT: {run_response_event.event}")
            print(f"MEMBER TOOL CALL: {run_response_event.tool.tool_name}")
            print(f"MEMBER TOOL CALL RESULT: {run_response_event.tool.result}")

        if run_response_event.event in [TeamRunEvent.run_response_content]:
            if not content_started:
                print("TEAM CONTENT:")
                content_started = True
            print(run_response_event.content, end="")

        if run_response_event.event in [RunEvent.run_response_content]:
            if not member_content_started:
                print("MEMBER CONTENT:")
                member_content_started = True
            print(run_response_event.content, end="")


if __name__ == "__main__":
    asyncio.run(
        run_team_with_events(
            "What is the current stock price of NVDA?",
        )
    )

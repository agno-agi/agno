import asyncio

from agno.agent import RunEvent
from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.tools.yfinance import YFinanceTools

finance_agent = Agent(
    agent_id="finance-agent",
    name="Finance Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[YFinanceTools()],
)


async def run_agent_with_events(prompt: str):
    content_started = False
    async for run_response_event in await finance_agent.arun(
        prompt,
        stream=True,
        stream_intermediate_steps=True,
    ):
        if run_response_event.event in [RunEvent.run_started, RunEvent.run_completed]:
            print(f"\nEVENT: {run_response_event.event}")

        if run_response_event.event in [RunEvent.tool_call_started]:
            print(f"\nEVENT: {run_response_event.event}")
            print(f"TOOL CALL: {run_response_event.tool.tool_name}")
            print(f"TOOL CALL ARGS: {run_response_event.tool.tool_args}")

        if run_response_event.event in [RunEvent.tool_call_completed]:
            print(f"\nEVENT: {run_response_event.event}")
            print(f"TOOL CALL: {run_response_event.tool.tool_name}")
            print(f"TOOL CALL RESULT: {run_response_event.tool.result}")

        if run_response_event.event in [RunEvent.run_response_content]:
            if not content_started:
                print("\nCONTENT:")
                content_started = True
            else:
                print(run_response_event.content, end="")


if __name__ == "__main__":
    asyncio.run(
        run_agent_with_events(
            "What is the price of Apple stock?",
        )
    )

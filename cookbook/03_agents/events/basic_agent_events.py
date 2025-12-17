import asyncio

from agno.agent import RunEvent
from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.tools.yfinance import YFinanceTools

finance_agent = Agent(
    id="finance-agent",
    name="Finance Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[YFinanceTools()],
)


async def run_agent_with_events(prompt: str):
    content_started = False
    async for run_output_event in finance_agent.arun(
        prompt,
        stream=True,
        stream_events=True,
    ):
        if run_output_event.event in [RunEvent.run_started, RunEvent.run_completed]:
            print(f"\nEVENT: {run_output_event.event}")

        if run_output_event.event in [RunEvent.tool_call_started]:
            print(f"\nEVENT: {run_output_event.event}")
            print(f"TOOL CALL: {run_output_event.tool.tool_name}")  # type: ignore
            print(f"TOOL CALL ARGS: {run_output_event.tool.tool_args}")  # type: ignore

        if run_output_event.event in [RunEvent.tool_call_completed]:
            print(f"\nEVENT: {run_output_event.event}")
            print(f"TOOL CALL: {run_output_event.tool.tool_name}")  # type: ignore
            print(f"TOOL CALL RESULT: {run_output_event.tool.result}")  # type: ignore

        if run_output_event.event in [RunEvent.run_content]:
            if not content_started:
                print("\nCONTENT:")
                content_started = True
            else:
                print(run_output_event.content, end="")


if __name__ == "__main__":
    asyncio.run(
        run_agent_with_events(
            "What is the price of Apple stock?",
        )
    )

"""Steer a running agent: send the user's follow-up while the run is still working.

The user asks about one city, then, while the weather tool is still running,
changes their mind and asks for a comparison. ``asteer()`` hands that message
to the running run. It joins the conversation right after the tool result, so
the model's next request already includes it and the answer covers both.
"""

import asyncio
import time

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunEvent


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    time.sleep(2)  # A slow tool gives the user time to send a follow-up
    return f"It is 18C and sunny in {city}."


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[get_weather],
    instructions="Answer weather questions using the get_weather tool.",
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def main() -> None:
    async for event in agent.arun(
        "What is the weather in Paris?", stream=True, stream_events=True
    ):
        if event.event == RunEvent.tool_call_started.value:
            # The user sends a follow-up while the tool is still running
            accepted = await agent.asteer(
                event.run_id, "Also check London and compare the two."
            )
            print(f"\n[steer accepted: {accepted}]")
        elif event.event == RunEvent.run_steered.value:
            print(f"[steered into the run: {event.content}]\n")
        elif event.event == RunEvent.run_content.value and event.content:
            print(event.content, end="", flush=True)
    print()


if __name__ == "__main__":
    asyncio.run(main())

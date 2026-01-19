import asyncio

from agno.agent import Agent
from agno.models.azure.openai_chat import AzureOpenAI
from agno.run.agent import RunEvent  # noqa


async def streaming_reasoning():
    """Test streaming reasoning with a Azure OpenAI model."""
    # Create an agent with reasoning enabled
    agent = Agent(
        reasoning_model=AzureOpenAI(id="gpt-4.1"),
        reasoning=True,
        instructions="Think step by step about the problem.",
    )

    prompt = "What is 25 * 37? Show your reasoning."

    await agent.aprint_response(prompt, stream=True, stream_events=True)

    # Use manual event loop to see all events
    # async for run_output_event in agent.arun(
    #     prompt,
    #     stream=True,
    #     stream_events=True,
    # ):
    #     if run_output_event.event == RunEvent.run_started:
    #         print(f"\nEVENT: {run_output_event.event}")

    #     elif run_output_event.event == RunEvent.reasoning_started:
    #         print(f"\nEVENT: {run_output_event.event}")
    #         print("Reasoning started...\n")

    #     elif run_output_event.event == RunEvent.reasoning_content_delta:
    #         # This is the NEW streaming event for reasoning content
    #         print(run_output_event.reasoning_content, end="", flush=True)

    #     elif run_output_event.event == RunEvent.reasoning_step:
    #         print(f"\nEVENT: {run_output_event.event}")

    #     elif run_output_event.event == RunEvent.reasoning_completed:
    #         print(f"\n\nEVENT: {run_output_event.event}")

    #     elif run_output_event.event == RunEvent.run_content:
    #         if run_output_event.content:
    #             print(run_output_event.content, end="", flush=True)

    #     elif run_output_event.event == RunEvent.run_completed:
    #         print(f"\n\nEVENT: {run_output_event.event}")


if __name__ == "__main__":
    asyncio.run(streaming_reasoning())

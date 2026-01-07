"""
Test script for streaming reasoning content.

This demonstrates the new streaming reasoning feature where reasoning content
is streamed as it arrives instead of all at once.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.run.agent import RunEvent  # noqa

# Create an agent with reasoning enabled
agent = Agent(
    reasoning_model=Claude(
        id="claude-sonnet-4-5",
        thinking={"type": "enabled", "budget_tokens": 1024},
    ),
    reasoning=True,
    instructions="Think step by step about the problem.",
)

prompt = "What is 25 * 37? Show your reasoning."

agent.print_response(prompt, stream=True, stream_events=True)

# # or you can capture the event using
# for run_output_event in agent.run(
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
#         # It streams the raw content as it's being generated
#         print(run_output_event.reasoning_content, end="", flush=True)

#     elif run_output_event.event == RunEvent.run_content:
#         if run_output_event.content:
#             print(run_output_event.content, end="", flush=True)

#     elif run_output_event.event == RunEvent.run_completed:
#         print(f"\n\nEVENT: {run_output_event.event}")

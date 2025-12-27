from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunEvent  # noqa

# Create an agent with reasoning enabled
agent = Agent(
    reasoning_model=OpenAIResponses(
        id="o3-mini",
        reasoning_effort="low",
    ),
    reasoning=True,
    instructions="Think step by step about the problem.",
)

prompt = "Analyze the key factors that led to the signing of the Treaty of Versailles in 1919 Discuss the political, economic, and social impacts of the treaty on Germany and how it contributed to the onset of World War II. Provide a nuanced assessment that includes multiple historical perspectives."

agent.print_response(prompt, stream=True, stream_events=True)

# Use manual event loop to see all events
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

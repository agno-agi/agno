from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.v2.workflow import WorkflowRunEvent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.workflow.v2.step import Step
from agno.workflow.v2.workflow import Workflow

# Simple test workflow
simple_agent = Agent(
    name="Simple Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions="You are a helpful assistant.",
)

# Create workflow with event storage
simple_workflow = Workflow(
    name="Simple Test Workflow",
    steps=[
        Step(name="Simple Step", agent=simple_agent),
    ],
    store_events=True,  # Enable event storage
    # events_to_skip=[WorkflowRunEvent.step_started],
)

# Run with streaming and check for WorkflowCompletedEvent
print("=== Testing WorkflowCompletedEvent ===")

events_seen = []
for event in simple_workflow.run(
    message="Say hello",
    stream=True,
    stream_intermediate_steps=True,
):
    events_seen.append(event.event if hasattr(event, "event") else type(event).__name__)
    print(f"Event: {event.event if hasattr(event, 'event') else type(event).__name__}")

print(f"\nAll events seen: {events_seen}")

# Check stored events
if simple_workflow.run_response and simple_workflow.run_response.events:
    print(f"\nStored events count: {len(simple_workflow.run_response.events)}")
    for i, event in enumerate(simple_workflow.run_response.events):
        print(f"  {i + 1}. {event.event}")
else:
    print("\nNo events stored!")

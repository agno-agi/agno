from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.run.agent import (
    RunContentEvent,
    RunEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.workflow import WorkflowRunEvent, WorkflowRunOutput
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# Define agents for different tasks
news_agent = Agent(
    name="News Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    instructions="You are a news researcher. Get the latest tech news and summarize key points.",
)

search_agent = Agent(
    name="Search Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a search specialist. Find relevant information on given topics.",
)

analysis_agent = Agent(
    name="Analysis Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are an analyst. Analyze the provided information and give insights.",
)

summary_agent = Agent(
    name="Summary Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a summarizer. Create concise summaries of the provided content.",
)

research_step = Step(
    name="Research Step",
    agent=news_agent,
)

search_step = Step(
    name="Search Step",
    agent=search_agent,
)


def print_stored_events(run_response: WorkflowRunOutput, example_name):
    """Helper function to print stored events in a nice format"""
    print(f"\n--- {example_name} - Stored Events ---")
    if run_response.events:
        print(f"Total stored events: {len(run_response.events)}")
        for i, event in enumerate(run_response.events, 1):
            print(f"  {i}. {event.event}")
    else:
        print("No events stored")
    print()


print("=== Simple Step Workflow with Event Storage ===")
step_workflow = Workflow(
    name="Simple Step Workflow",
    description="Basic workflow demonstrating step event storage",
    db=SqliteDb(
        session_table="workflow_session",
        db_file="tmp/workflow.db",
    ),
    steps=[research_step, search_step],
    store_events=True,
    events_to_skip=[
        WorkflowRunEvent.step_started,
        WorkflowRunEvent.workflow_completed,
        RunEvent.run_content,
        RunEvent.run_started,
        RunEvent.run_completed,
    ],  # Skip step started events to reduce noise
)

print("Running Step workflow with streaming...")
for event in step_workflow.run(
    input="AI trends in 2024",
    stream=True,
    stream_events=True,
):
    # Filter out RunContentEvent from printing to reduce noise
    if not isinstance(
        event, (RunContentEvent, ToolCallStartedEvent, ToolCallCompletedEvent)
    ):
        print(
            f"Event: {event.event if hasattr(event, 'event') else type(event).__name__}"
        )
run_response = step_workflow.get_last_run_output()

print("\nStep workflow completed!")
print(
    f"Total events stored: {len(run_response.events) if run_response and run_response.events else 0}"
)

# Print stored events in a nice format
print_stored_events(run_response, "Simple Step Workflow")

# ------------------------------------------------------------------------------------------------ #
# ------------------------------------------------------------------------------------------------ #

# Example 2: Parallel Primitive with Event Storage
print("=== 2. Parallel Example ===")
parallel_workflow = Workflow(
    name="Parallel Research Workflow",
    steps=[
        Parallel(
            Step(name="News Research", agent=news_agent),
            Step(name="Web Search", agent=search_agent),
            name="Parallel Research",
        ),
        Step(name="Combine Results", agent=analysis_agent),
    ],
    db=SqliteDb(
        session_table="workflow_parallel",
        db_file="tmp/workflow_parallel.db",
    ),
    store_events=True,
    events_to_skip=[
        WorkflowRunEvent.parallel_execution_started,
        WorkflowRunEvent.parallel_execution_completed,
    ],
)

print("Running Parallel workflow...")
for event in parallel_workflow.run(
    input="Research machine learning developments",
    stream=True,
    stream_events=True,
):
    # Filter out RunContentEvent from printing
    if not isinstance(event, RunContentEvent):
        print(
            f"Event: {event.event if hasattr(event, 'event') else type(event).__name__}"
        )

run_response = parallel_workflow.get_last_run_output()
print(f"Parallel workflow stored {len(run_response.events)} events")
print_stored_events(run_response, "Parallel Workflow")
print()

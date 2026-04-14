"""
Nested Workflow Example - Event Inspection

Runs a nested workflow and prints every workflow/step event with full details
so you can see workflow_id, workflow_name, nested_depth, and
how inner vs outer events differ.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.run.workflow import (
    BaseWorkflowRunOutputEvent,
    StepCompletedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowStartedEvent,
)
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


def create_summary(step_input: StepInput) -> StepOutput:
    """A simple function step that summarizes the previous step's output"""
    previous_content = step_input.get_last_step_content()
    summary = (
        f"Summary of research:\n{previous_content[:500]}..."
        if previous_content
        else "No content to summarize"
    )
    return StepOutput(content=summary)


# --- Inner workflow ---
research_agent = Agent(
    name="Research Agent",
    model=Claude(id="claude-sonnet-4-20250514"),
    instructions="You are a research assistant. Provide concise, factual information in 2-3 sentences.",
)

inner_workflow = Workflow(
    name="Inner Workflow",
    description="A simple workflow that researches a topic",
    steps=[
        Step(name="research", agent=research_agent),
        Step(name="summary", executor=create_summary),
    ],
)

# --- Outer workflow ---
writer_agent = Agent(
    name="Writer Agent",
    model=Claude(id="claude-sonnet-4-20250514"),
    instructions="You are a professional writer. Take the research provided and write a short polished paragraph.",
)

outer_workflow = Workflow(
    name="Outer Workflow",
    description="A workflow that researches a topic and then writes about it",
    steps=[
        Step(name="research_phase", workflow=inner_workflow),
        Step(name="writing_phase", agent=writer_agent),
    ],
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
)


def print_event_details(event: BaseWorkflowRunOutputEvent, label: str) -> None:
    """Print key fields of a workflow event."""
    indent = "  " * getattr(event, "nested_depth", 0)
    print(f"\n{indent}{'=' * 60}")
    print(f"{indent}[{label}]")
    print(f"{indent}  event type       : {type(event).__name__}")
    print(f"{indent}  workflow_id       : {getattr(event, 'workflow_id', None)}")
    print(f"{indent}  workflow_name     : {getattr(event, 'workflow_name', None)}")
    print(f"{indent}  nested_depth     : {getattr(event, 'nested_depth', None)}")
    print(f"{indent}  run_id           : {getattr(event, 'run_id', None)}")
    print(f"{indent}  session_id       : {getattr(event, 'session_id', None)}")
    print(f"{indent}  step_id          : {getattr(event, 'step_id', None)}")
    print(f"{indent}  step_name        : {getattr(event, 'step_name', None)}")
    print(f"{indent}  step_index       : {getattr(event, 'step_index', None)}")

    # Extra fields for specific event types
    if isinstance(event, (StepCompletedEvent, WorkflowCompletedEvent)):
        content = getattr(event, "content", None)
        if content:
            preview = str(content)[:120].replace("\n", " ")
            print(f"{indent}  content (preview) : {preview}...")

    if isinstance(event, WorkflowCompletedEvent):
        step_results = getattr(event, "step_results", None)
        if step_results:
            print(f"{indent}  step_results count: {len(step_results)}")
            for i, sr in enumerate(step_results):
                sr_name = getattr(sr, "step_name", None) or f"step_{i}"
                sr_type = getattr(sr, "executor_type", "?")
                sr_metrics = getattr(sr, "metrics", None)
                print(
                    f"{indent}    [{i}] {sr_name} (type={sr_type}, metrics={sr_metrics is not None})"
                )

    print(f"{indent}{'=' * 60}")


if __name__ == "__main__":
    print("Running nested workflow example with event inspection...")
    print("=" * 60)

    EVENT_TYPES = (
        WorkflowStartedEvent,
        WorkflowCompletedEvent,
        StepStartedEvent,
        StepCompletedEvent,
    )

    event_log = []

    for event in outer_workflow.run(
        input="Tell me about the history of artificial intelligence",
        stream=True,
        stream_events=True,
    ):
        if isinstance(event, EVENT_TYPES):
            label = type(event).__name__
            # Tag inner vs outer
            source = getattr(event, "workflow_name", None) or "?"
            current = getattr(event, "workflow_name", None) or "?"
            depth = getattr(event, "nested_depth", 0)
            if depth > 0:
                label = f"INNER (depth={depth}, source={source}) | {label}"
            else:
                label = f"OUTER (source={source}) | {label}"
            print_event_details(event, label)
            event_log.append(event)

    # --- Summary ---
    print("\n\n" + "=" * 60)
    print("EVENT SUMMARY")
    print("=" * 60)
    print(f"Total workflow/step events captured: {len(event_log)}")
    for i, ev in enumerate(event_log):
        depth = getattr(ev, "nested_depth", 0)
        source = getattr(ev, "workflow_name", None) or "?"
        indent = "  " * depth
        print(
            f"  {i + 1}. {indent}{type(ev).__name__:<30s} depth={depth}  source={source}"
        )

"""
This example demonstrates how to access and analyze workflow metrics.

Shows how to retrieve detailed metrics for workflow execution, including
workflow-level metrics, step-level metrics, and session metrics.

Prerequisites:
1. Run: cookbook/run_pgvector.sh (to start PostgreSQL)
2. Ensure PostgreSQL is running on localhost:5532
"""

import asyncio
from textwrap import dedent
from typing import AsyncIterator

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.utils.pprint import pprint_run_response
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow
from rich.pretty import pprint

# Database configuration for metrics storage
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, session_table="workflow_metrics_sessions")

# Define agents
web_agent = Agent(
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    role="Search the web for the latest news and trends",
)
hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    role="Extract key insights and content from Hackernews posts",
)

writer_agent = Agent(
    name="Writer Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Write a blog post on the topic",
)


async def prepare_input_for_web_search(
    step_input: StepInput,
) -> AsyncIterator[StepOutput]:
    """Generator function that yields StepOutput"""
    topic = step_input.input

    # Create proper StepOutput content
    content = dedent(f"""\
        I'm writing a blog post on the topic
        <topic>
        {topic}
        </topic>

        Search the web for atleast 10 articles\
        """)

    # Yield a StepOutput as the final result
    yield StepOutput(content=content)


async def prepare_input_for_writer(step_input: StepInput) -> AsyncIterator[StepOutput]:
    """Generator function that yields StepOutput"""
    topic = step_input.input
    research_team_output = step_input.previous_step_content

    # Create proper StepOutput content
    content = dedent(f"""\
        I'm writing a blog post on the topic:
        <topic>
        {topic}
        </topic>

        Here is information from the web:
        <research_results>
        {research_team_output}
        </research_results>\
        """)

    # Yield a StepOutput as the final result
    yield StepOutput(content=content)


# Define research team for complex analysis
research_team = Team(
    name="Research Team",
    members=[hackernews_agent, web_agent],
    instructions="Research tech topics from Hackernews and the web",
)


async def main():
    content_creation_workflow = Workflow(
        name="Blog Post Workflow",
        description="Automated blog post creation from Hackernews and the web",
        steps=[
            prepare_input_for_web_search,
            research_team,
            prepare_input_for_writer,
            writer_agent,
        ],
        db=db,
        session_id="workflow_metrics_demo",
    )

    # Run workflow and get the final output (non-streaming to get WorkflowRunOutput directly)
    workflow_run_output = await content_creation_workflow.arun(
        input="AI trends in 2024",
        markdown=True,
    )

    # Print workflow response
    if workflow_run_output:
        pprint_run_response(workflow_run_output, markdown=True)

    print("\n" + "=" * 80)
    print("1. WORKFLOW METRICS (WorkflowMetrics class - workflow-level aggregation)")
    print("=" * 80)
    if workflow_run_output and workflow_run_output.metrics:
        print(f"Type: {type(workflow_run_output.metrics).__name__}")
        metrics_dict = workflow_run_output.metrics.to_dict()
        pprint(metrics_dict)

        print("\nWorkflow-level stats:")
        if workflow_run_output.metrics.duration:
            print(
                f"  Total workflow duration: {workflow_run_output.metrics.duration:.4f}s"
            )
        print(f"  Number of steps: {len(workflow_run_output.metrics.steps)}")
    else:
        print("No workflow metrics available")

    print("\n" + "=" * 80)
    print("2. STEP METRICS (StepMetrics class - per-step execution metrics)")
    print("=" * 80)
    if workflow_run_output and workflow_run_output.metrics:
        for step_name, step_metrics in workflow_run_output.metrics.steps.items():
            print(f"\nStep: {step_name}")
            print(f"  Executor Type: {step_metrics.executor_type}")
            print(f"  Executor Name: {step_metrics.executor_name}")
            if step_metrics.metrics:
                print(f"  Metrics Type: {type(step_metrics.metrics).__name__}")
                pprint(step_metrics.metrics.to_dict())

                # Show per-model metrics breakdown if details exist
                if step_metrics.metrics.details:
                    print("\n  " + "-" * 76)
                    print("  PER-MODEL METRICS (details field):")
                    print("  " + "-" * 76)
                    for (
                        model_type,
                        model_metrics_list,
                    ) in step_metrics.metrics.details.items():
                        print(f"\n  {model_type}:")
                        for i, model_metrics in enumerate(model_metrics_list, 1):
                            print(f"    Instance {i}:")
                            pprint(model_metrics.to_dict())
            else:
                print("  No metrics (function steps don't have metrics)")
    else:
        print("No step metrics available")

    print("\n" + "=" * 80)
    print("3. STEP OUTPUT METRICS (from step_results)")
    print("=" * 80)
    if workflow_run_output and workflow_run_output.step_results:
        for i, step_result in enumerate(workflow_run_output.step_results, 1):
            print(f"\nStep Result {i}: {step_result.step_name or 'Unknown'}")
            if step_result.metrics:
                print(f"  Metrics Type: {type(step_result.metrics).__name__}")
                pprint(step_result.metrics.to_dict())
            else:
                print("  No metrics")
    else:
        print("No step results available")

    print("\n" + "=" * 80)
    print("4. SESSION METRICS (Metrics class - aggregated across all runs)")
    print("=" * 80)
    try:
        # Check if database supports async operations
        if (
            hasattr(content_creation_workflow, "_has_async_db")
            and content_creation_workflow._has_async_db()
        ):
            # Use async method for async databases
            session_metrics = await content_creation_workflow.aget_session_metrics()
        else:
            # Use sync method for sync databases (run in executor to avoid blocking)
            import asyncio

            session_metrics = await asyncio.to_thread(
                content_creation_workflow.get_session_metrics
            )

        if session_metrics:
            print(f"Type: {type(session_metrics).__name__}")
            pprint(session_metrics.to_dict())

            print("\nSession-level stats:")
            print(f"  Total tokens: {session_metrics.total_tokens}")
            print(f"  Input tokens: {session_metrics.input_tokens}")
            print(f"  Output tokens: {session_metrics.output_tokens}")
        else:
            print("No session metrics available")
    except Exception as e:
        print(f"Could not retrieve session metrics: {e}")
        print(
            "Note: Session metrics are created after the first workflow run completes."
        )
        print(
            "      Make sure the workflow has a database configured and the session was saved."
        )

    print("\n" + "=" * 80)
    print("5. WORKFLOW RUN SUMMARY")
    print("=" * 80)
    if workflow_run_output:
        print(f"Workflow Name: {workflow_run_output.workflow_name}")
        print(f"Workflow ID: {workflow_run_output.workflow_id}")
        print(f"Run ID: {workflow_run_output.run_id}")
        print(f"Status: {workflow_run_output.status}")
        if workflow_run_output.metrics and workflow_run_output.metrics.duration:
            print(f"Total Duration: {workflow_run_output.metrics.duration:.4f}s")
            print(f"Steps Executed: {len(workflow_run_output.metrics.steps)}")
    else:
        print("No workflow run output available")


if __name__ == "__main__":
    asyncio.run(main())

"""
Demonstrates that the @pause decorator works correctly with async functions.

The @pause decorator attaches metadata directly to the function without
creating a wrapper, so async functions retain their async nature.

This example shows:
1. An async step function decorated with @pause
2. Using acontinue_run for async workflow continuation
3. Simulating async I/O operations within the step
"""

import asyncio

from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb
from agno.models.openai import OpenAIChat
from agno.workflow.decorators import pause
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
async_db_url = "postgresql+psycopg_async://ai:ai@localhost:5532/ai"


# ============================================================
# Step 1: Research Agent
# ============================================================
research_agent = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a research assistant.",
        "Given a topic, provide 3 key points about it.",
    ],
)


# ============================================================
# Step 2: Async processing step with @pause decorator
# ============================================================
@pause(
    name="Async Data Processor",
    requires_confirmation=True,
    confirmation_message="Research gathered. Ready to process asynchronously. Continue?",
)
async def async_process_data(step_input: StepInput) -> StepOutput:
    """
    Async step function that simulates async I/O operations.

    The @pause decorator works correctly with async functions because
    it attaches metadata directly to the function without wrapping it.
    """
    research = step_input.previous_step_content or "No research"

    # Simulate async I/O (e.g., API call, database query)
    await asyncio.sleep(0.5)

    processed = f"ASYNC PROCESSED:\n{research}\n\n[Processed with async I/O simulation]"

    return StepOutput(content=processed)


# ============================================================
# Step 3: Writer Agent
# ============================================================
writer_agent = Agent(
    name="Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a content writer.",
        "Write a brief summary based on the processed research.",
    ],
)


# Define steps
research_step = Step(name="research", agent=research_agent)
process_step = Step(name="async_process", executor=async_process_data)
write_step = Step(name="write", agent=writer_agent)

# Create workflow with async database for proper async support
workflow = Workflow(
    name="async_hitl_workflow",
    db=AsyncPostgresDb(db_url=async_db_url),
    steps=[research_step, process_step, write_step],
)


async def main():
    print("Starting async HITL workflow...")
    print("=" * 50)

    # Run workflow asynchronously
    run_output = await workflow.arun("Benefits of meditation")

    # Handle HITL pause
    while run_output.is_paused:
        for requirement in run_output.steps_requiring_confirmation:
            print(f"\n[HITL] Step '{requirement.step_name}' requires confirmation")
            print(f"[HITL] {requirement.confirmation_message}")

            # In a real app, this would be async user input
            # For demo, we auto-confirm
            print("[HITL] Auto-confirming for demo...")
            requirement.confirm()

        # Continue workflow asynchronously
        run_output = await workflow.acontinue_run(run_output)

    print("\n" + "=" * 50)
    print(f"Status: {run_output.status}")
    print(f"Output:\n{run_output.content}")


if __name__ == "__main__":
    asyncio.run(main())

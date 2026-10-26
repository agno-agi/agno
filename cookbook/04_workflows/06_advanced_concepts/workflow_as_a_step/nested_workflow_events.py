"""
Nested Workflow Example - Event Inspection with AgentOS

Serves a nested workflow through AgentOS so you can inspect every
workflow/step event streamed over SSE and see workflow_id, workflow_name,
nested_depth, and how inner vs outer events differ.

Try: Start the server, then stream a run and watch the events:

    curl -N -X POST http://localhost:7777/workflows/outer-workflow/runs \
        -F "message=Tell me about the history of artificial intelligence" \
        -F "stream=true"

Inner workflow events carry nested_depth > 0 and workflow_name="Inner Workflow".
You can also connect the server to https://os.agno.com to view the run.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
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
    id="inner-workflow",
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
    id="outer-workflow",
    name="Outer Workflow",
    description="A workflow that researches a topic and then writes about it",
    steps=[
        Step(name="research_phase", workflow=inner_workflow),
        Step(name="writing_phase", agent=writer_agent),
    ],
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="nested-workflow-events",
    description="AgentOS serving a nested workflow for event inspection.",
    workflows=[outer_workflow],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="nested_workflow_events:app", reload=True)

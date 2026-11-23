"""
Research Workflow - A Deterministic Research Pipeline
=====================================================

A Team decides how to coordinate; a Workflow runs the same ordered steps
every time. This pipeline always: (1) gathers sources with Parallel Search
and Extract, then (2) synthesizes a cited brief from what it found.

Use a workflow when you want a repeatable, auditable research process.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Setup - step agents
# ---------------------------------------------------------------------------
# Step 1: gather raw material from the web.
source_gatherer = Agent(
    name="Source Gatherer",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools(enable_search=True, enable_extract=True)],
    instructions=[
        "Search the web for the topic and gather the most relevant sources.",
        "Return key facts as bullet points, each with its source URL.",
    ],
)

# Step 2: turn the raw material into a clean, cited brief.
report_writer = Agent(
    name="Report Writer",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions=[
        "Write a concise research brief from the gathered sources.",
        "Keep every claim tied to a source URL.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create the Workflow
# ---------------------------------------------------------------------------
research_pipeline = Workflow(
    name="Research Pipeline",
    description="Gather sources, then synthesize a cited research brief.",
    db=SqliteDb(db_file="tmp/parallel_workflow.db"),
    steps=[
        Step(name="Gather Sources", agent=source_gatherer),
        Step(name="Write Brief", agent=report_writer),
    ],
)

# ---------------------------------------------------------------------------
# Run the Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    research_pipeline.print_response(
        input="How are AI agents changing web search in 2026?",
        markdown=True,
    )

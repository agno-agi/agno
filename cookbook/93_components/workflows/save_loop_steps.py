"""
Save Loop Workflow Steps
========================

Demonstrates creating a workflow with loop steps, saving it to the database,
and loading it back with a Registry.
"""

from typing import List

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.registry import Registry
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow.loop import Loop
from agno.workflow.step import Step
from agno.workflow.types import StepOutput
from agno.workflow.workflow import Workflow, get_workflow_by_id

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
# Agents
research_agent = Agent(
    name="Research Agent",
    instructions="Research the given topic thoroughly using available tools",
    tools=[HackerNewsTools(), WebSearchTools()],
)

summary_agent = Agent(
    name="Summary Agent",
    instructions="Summarize the research findings into a concise report",
)


# ---------------------------------------------------------------------------
# Create Registry Components
# ---------------------------------------------------------------------------
# End condition function (will be serialized by name and restored via registry)
def check_research_complete(outputs: List[StepOutput]) -> bool:
    """Returns True to break the loop, False to continue."""
    if not outputs:
        return False

    for output in outputs:
        if output.content and len(output.content) > 500:
            print(f"Loop: Research complete - found {len(output.content)} chars")
            return True

    print("Loop: Research incomplete - continuing")
    return False


# Registry (required to restore the end_condition function when loading)
registry = Registry(
    name="Loop Workflow Registry",
    functions=[check_research_complete],
)

# ---------------------------------------------------------------------------
# Create Workflow Steps
# ---------------------------------------------------------------------------
# Steps
research_step = Step(
    name="ResearchStep",
    description="Research the topic using HackerNews and web search",
    agent=research_agent,
)

summarize_step = Step(
    name="SummarizeStep",
    description="Summarize all research findings",
    agent=summary_agent,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
# Workflow
workflow = Workflow(
    name="Loop Research Workflow",
    description="Research a topic in a loop until sufficient content is gathered",
    steps=[
        Loop(
            name="ResearchLoop",
            description="Loop through research until end condition is met",
            steps=[research_step],
            end_condition=check_research_complete,
            max_iterations=3,
        ),
        summarize_step,
    ],
    db=db,
)

# ---------------------------------------------------------------------------
# Run Workflow Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Save
    print("Saving workflow...")
    version = workflow.save(db=db)
    print(f"Saved workflow as version {version}")

    # Load
    print("\nLoading workflow...")
    loaded_workflow = get_workflow_by_id(
        db=db,
        id="loop-research-workflow",
        registry=registry,
    )

    if loaded_workflow:
        print("Workflow loaded successfully!")
        print(f"  Name: {loaded_workflow.name}")
        print(f"  Steps: {len(loaded_workflow.steps) if loaded_workflow.steps else 0}")

        # Uncomment to run the loaded workflow
        # loaded_workflow.print_response(input="Latest developments in AI agents", stream=True)
    else:
        print("Workflow not found")

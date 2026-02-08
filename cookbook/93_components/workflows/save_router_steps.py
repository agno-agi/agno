"""
Save Router Workflow Steps
==========================

Demonstrates creating a workflow with router steps, saving it to the
database, and loading it back with a Registry.
"""

from typing import List

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.registry import Registry
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput
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
hackernews_agent = Agent(
    name="HackerNews Agent",
    instructions="Research tech news and trends from Hacker News",
    tools=[HackerNewsTools()],
)

web_agent = Agent(
    name="Web Agent",
    instructions="Research general information from the web",
    tools=[WebSearchTools()],
)

summary_agent = Agent(
    name="Summary Agent",
    instructions="Summarize the research findings into a concise report",
)

# ---------------------------------------------------------------------------
# Create Workflow Steps
# ---------------------------------------------------------------------------
# Steps
hackernews_step = Step(
    name="HackerNewsStep",
    description="Research using HackerNews for tech topics",
    agent=hackernews_agent,
)

web_step = Step(
    name="WebStep",
    description="Research using web search for general topics",
    agent=web_agent,
)

summary_step = Step(
    name="SummaryStep",
    description="Summarize the research",
    agent=summary_agent,
)


# ---------------------------------------------------------------------------
# Create Registry Components
# ---------------------------------------------------------------------------
# Selector function (will be serialized by name and restored via registry)
def select_research_step(step_input: StepInput) -> List[Step]:
    """Dynamically select which research step(s) to execute based on the input."""
    topic = step_input.input or step_input.previous_step_content or ""
    topic_lower = topic.lower()
    tech_keywords = [
        "ai",
        "machine learning",
        "programming",
        "software",
        "tech",
        "startup",
        "coding",
    ]

    selected_steps = []

    if any(keyword in topic_lower for keyword in tech_keywords):
        print("Router: Selected HackerNews step for tech topic")
        selected_steps.append(hackernews_step)

    if not selected_steps or "news" in topic_lower or "general" in topic_lower:
        print("Router: Selected Web step")
        selected_steps.append(web_step)

    return selected_steps


# Registry (required to restore the selector function when loading)
registry = Registry(
    name="Router Workflow Registry",
    functions=[select_research_step],
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
# Workflow
workflow = Workflow(
    name="Router Research Workflow",
    description="Dynamically route to appropriate research steps based on topic",
    steps=[
        Router(
            name="ResearchRouter",
            description="Route to appropriate research agent based on topic",
            selector=select_research_step,
            choices=[hackernews_step, web_step],
        ),
        summary_step,
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
        id="router-research-workflow",
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

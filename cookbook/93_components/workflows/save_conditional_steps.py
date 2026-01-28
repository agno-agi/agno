"""
Example: Saving and Loading a Workflow with Condition

This example demonstrates how to:
1. Create a workflow with a Condition that evaluates whether to run steps
2. Save the workflow to a database
3. Load the workflow back using a registry to restore the evaluator function
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.registry import Registry
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow, get_workflow_by_id

# Database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Agents
hackernews_agent = Agent(
    name="HackerNews Researcher",
    instructions="Research tech news and trends from Hacker News",
    tools=[HackerNewsTools()],
)

web_agent = Agent(
    name="Web Researcher",
    instructions="Research general information from the web",
    tools=[WebSearchTools()],
)

content_agent = Agent(
    name="Content Creator",
    instructions="Create well-structured content from research data",
)


# Evaluator function (will be serialized by name and restored via registry)
def is_tech_topic(step_input: StepInput) -> bool:
    """Returns True to execute the conditional steps, False to skip."""
    topic = step_input.input or step_input.previous_step_content or ""
    tech_keywords = [
        "ai",
        "machine learning",
        "programming",
        "software",
        "tech",
        "startup",
        "coding",
    ]
    is_tech = any(keyword in topic.lower() for keyword in tech_keywords)
    print(f"Condition: Topic is {'tech' if is_tech else 'not tech'}")
    return is_tech


# Registry (required to restore the evaluator function when loading)
registry = Registry(
    name="Condition Workflow Registry",
    functions=[is_tech_topic],
)

# Steps
research_hackernews_step = Step(
    name="ResearchHackerNews",
    description="Research tech news from Hacker News",
    agent=hackernews_agent,
)

research_web_step = Step(
    name="ResearchWeb",
    description="Research general information from web",
    agent=web_agent,
)

write_step = Step(
    name="WriteContent",
    description="Write the final content based on research",
    agent=content_agent,
)

# Workflow
workflow = Workflow(
    name="Conditional Research Workflow",
    description="Conditionally research from HackerNews for tech topics",
    steps=[
        Condition(
            name="TechTopicCondition",
            description="Check if topic is tech-related for HackerNews research",
            evaluator=is_tech_topic,
            steps=[research_hackernews_step],
        ),
        research_web_step,
        write_step,
    ],
    db=db,
)

if __name__ == "__main__":
    # Save
    print("Saving workflow...")
    version = workflow.save(db=db)
    print(f"Saved workflow as version {version}")

    # Load
    print("\nLoading workflow...")
    loaded_workflow = get_workflow_by_id(
        db=db,
        id="conditional-research-workflow",
        registry=registry,
    )

    if loaded_workflow:
        print("Workflow loaded successfully!")
        print(f"  Name: {loaded_workflow.name}")
        print(f"  Steps: {len(loaded_workflow.steps) if loaded_workflow.steps else 0}")

        # Uncomment to run the loaded workflow
        # loaded_workflow.print_response(input="Latest AI developments in machine learning", stream=True)
    else:
        print("Workflow not found")

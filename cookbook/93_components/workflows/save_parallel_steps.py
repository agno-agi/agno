"""
Example: Saving and Loading a Workflow with Parallel Steps

This example demonstrates how to:
1. Create a workflow with Parallel steps that run concurrently
2. Save the workflow to a database
3. Load the workflow back and run it
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow, get_workflow_by_id

# Database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Agents
hackernews_researcher = Agent(
    name="HackerNews Researcher",
    instructions="Research tech news and trends from Hacker News",
    tools=[HackerNewsTools()],
)

web_researcher = Agent(
    name="Web Researcher",
    instructions="Research general information from the web",
    tools=[WebSearchTools()],
)

writer = Agent(
    name="Content Writer",
    instructions="Write well-structured content from research findings",
)

reviewer = Agent(
    name="Content Reviewer",
    instructions="Review and improve the written content",
)

# Steps
research_hn_step = Step(
    name="ResearchHackerNews",
    description="Research tech news from Hacker News",
    agent=hackernews_researcher,
)

research_web_step = Step(
    name="ResearchWeb",
    description="Research information from the web",
    agent=web_researcher,
)

write_step = Step(
    name="WriteArticle",
    description="Write article from research findings",
    agent=writer,
)

review_step = Step(
    name="ReviewArticle",
    description="Review and finalize the article",
    agent=reviewer,
)

# Workflow
workflow = Workflow(
    name="Parallel Research Pipeline",
    description="Research from multiple sources in parallel, then write and review",
    steps=[
        Parallel(
            research_hn_step,
            research_web_step,
            name="ParallelResearch",
            description="Run HackerNews and Web research in parallel",
        ),
        write_step,
        review_step,
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
    loaded_workflow = get_workflow_by_id(db=db, id="parallel-research-pipeline")

    if loaded_workflow:
        print("Workflow loaded successfully!")
        print(f"  Name: {loaded_workflow.name}")
        print(f"  Steps: {len(loaded_workflow.steps) if loaded_workflow.steps else 0}")

        # Uncomment to run the loaded workflow
        # loaded_workflow.print_response(input="Latest developments in AI agents")
    else:
        print("Workflow not found")

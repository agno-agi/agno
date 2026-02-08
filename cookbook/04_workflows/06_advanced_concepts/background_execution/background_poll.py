"""
Background Poll
===============

Demonstrates running a workflow in async background mode and polling run status until completion.
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.utils.pprint import pprint_run_response
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    role="Extract key insights and content from Hackernews posts",
)

web_agent = Agent(
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[WebSearchTools()],
    role="Search the web for the latest news and trends",
)

content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Plan a content schedule over 4 weeks for the provided topic and research content",
        "Ensure that I have posts for 3 posts per week",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
research_team = Team(
    name="Research Team",
    members=[hackernews_agent, web_agent],
    instructions="Research tech topics from Hackernews and the web",
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_step = Step(
    name="Research Step",
    team=research_team,
)

content_planning_step = Step(
    name="Content Planning Step",
    agent=content_planner,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
content_creation_workflow = Workflow(
    name="Content Creation Workflow",
    description="Automated content creation from blog posts to social media",
    db=SqliteDb(
        session_table="workflow_session",
        db_file="tmp/workflow.db",
    ),
    steps=[research_step, content_planning_step],
)


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
async def main() -> None:
    print("Starting Async Background Workflow Test")

    bg_response = await content_creation_workflow.arun(
        input="AI trends in 2024",
        background=True,
    )
    print(f"Initial Response: {bg_response.status} - {bg_response.content}")
    print(f"Run ID: {bg_response.run_id}")

    poll_count = 0

    while True:
        poll_count += 1
        print(f"\nPoll #{poll_count} (every 5s)")

        result = content_creation_workflow.get_run(bg_response.run_id)

        if result is None:
            print("Workflow not found yet, still waiting...")
            if poll_count > 50:
                print(f"Timeout after {poll_count} attempts")
                break
            await asyncio.sleep(5)
            continue

        if result.has_completed():
            break

        if poll_count > 200:
            print(f"Timeout after {poll_count} attempts")
            break

        await asyncio.sleep(5)

    final_result = content_creation_workflow.get_run(bg_response.run_id)

    print("\nFinal Result:")
    print("=" * 50)
    pprint_run_response(final_result, markdown=True)


if __name__ == "__main__":
    asyncio.run(main())

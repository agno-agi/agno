import json

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools import tool
from agno.utils import pprint
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow
from rich.console import Console
from rich.prompt import Prompt

console = Console()


# This tool will require user confirmation before execution
@tool(requires_confirmation=True)
def get_top_hackernews_stories(num_stories: int) -> str:
    """Fetch top stories from Hacker News.

    Args:
        num_stories (int): Number of stories to retrieve

    Returns:
        str: JSON string containing story details
    """
    # Fetch top story IDs
    response = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json")
    story_ids = response.json()

    # Yield story details
    all_stories = []
    for story_id in story_ids[:num_stories]:
        story_response = httpx.get(
            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
        )
        story = story_response.json()
        if "text" in story:
            story.pop("text", None)
        all_stories.append(story)
    return json.dumps(all_stories)


# Define agents
content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-5-mini"),
    instructions=[
        "Plan a content schedule over 4 weeks for the provided topic and research content",
        "Ensure that I have posts for 3 posts per week",
    ],
    db=SqliteDb(db_file="tmp/workflow.db"),
)
hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[get_top_hackernews_stories],
    role="Extract key insights and content from Hackernews posts",
    db=SqliteDb(db_file="tmp/workflow.db"),
)

# Define Workflow steps
research_step = Step(
    name="Hackernews Research Step",
    agent=hackernews_agent,
)
content_planning_step = Step(
    name="Content Planning Step",
    agent=content_planner,
)

# Define our Workflow
content_creation_workflow = Workflow(
    name="Content Creation Workflow",
    description="Automated content creation from blog posts to social media",
    db=SqliteDb(db_file="tmp/workflow.db"),
    steps=[research_step, content_planning_step],
)

run_output = content_creation_workflow.run(input="AI news from this week")

for requirement in run_output.active_requirements:
    if requirement.needs_confirmation:
        # Ask for confirmation
        console.print(
            f"Tool name [bold blue]{requirement.tool_execution.tool_name}({requirement.tool_execution.tool_args})[/] requires confirmation."
        )
        message = (
            Prompt.ask("Do you want to continue?", choices=["y", "n"], default="y")
            .strip()
            .lower()
        )
        if message == "n":
            requirement.reject()
        else:
            requirement.confirm()

run_output = content_creation_workflow.continue_run(
    run_id=run_output.run_id, requirements=run_output.requirements
)

pprint.pprint_run_response(run_output)

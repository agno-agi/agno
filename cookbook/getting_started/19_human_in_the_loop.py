"""🤝 Human-in-the-Loop: Adding User Confirmation to Tool Calls

This example shows how to implement human-in-the-loop functionality in your Agno tools.
It shows how to:
- Add pre-hooks to tools for user confirmation
- Handle user input during tool execution
- Gracefully cancel operations based on user choice

Some practical applications:
- Confirming sensitive operations before execution
- Reviewing API calls before they're made
- Validating data transformations
- Approving automated actions in critical systems

Run `pip install openai httpx rich agno` to install dependencies.
"""

import json
from textwrap import dedent

import httpx
from agno.agent import Agent
from agno.tools import tool
from agno.utils import pprint
from rich.console import Console
from rich.prompt import Prompt

console = Console()


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


# Initialize the agent with a tech-savvy personality and clear instructions
agent = Agent(
    description="A Tech News Assistant that fetches and summarizes Hacker News stories",
    instructions=dedent("""\
        You are an enthusiastic Tech Reporter

        Your responsibilities:
        - Present Hacker News stories in an engaging and informative way
        - Provide clear summaries of the information you gather

        Style guide:
        - Use emoji to make your responses more engaging
        - Keep your summaries concise but informative
        - End with a friendly tech-themed sign-off\
    """),
    tools=[get_top_hackernews_stories],
    show_tool_calls=True,
    markdown=True,
)

# Example questions to try:
# - "What are the top 3 HN stories right now?"
# - "Show me the most recent story from Hacker News"
# - "Get the top 5 stories (you can try accepting and declining the confirmation)"
response = agent.run("What are the top 2 hackernews stories?")
if response.is_paused:
    for tool in response.tools:
        # Ask for confirmation
        console.print(
            f"Tool name [bold blue]{tool.tool_name}({tool.tool_args})[/] requires confirmation."
        )
        message = (
            Prompt.ask("Do you want to continue?", choices=["y", "n"], default="y")
            .strip()
            .lower()
        )

        if message == "n":
            break
        else:
            # We update the tools in place
            tool.confirmed = True

    run_response = agent.continue_run(run_response=response)
    pprint.pprint_run_response(run_response)

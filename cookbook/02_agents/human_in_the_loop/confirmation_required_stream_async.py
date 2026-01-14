"""🤝 Human-in-the-Loop: Adding User Confirmation to Tool Calls

This example shows how to implement human-in-the-loop functionality in your Agno tools.
It shows how to:
- Handle user confirmation during tool execution
- Gracefully cancel operations based on user choice

Some practical applications:
- Confirming sensitive operations before execution
- Reviewing API calls before they're made
- Validating data transformations
- Approving automated actions in critical systems

Run `pip install openai httpx rich agno` to install dependencies.
"""

import asyncio
import json

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools import tool
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


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[get_top_hackernews_stories],
    db=SqliteDb(session_table="test_session", db_file="tmp/example.db"),
    markdown=True,
)


async def main():
    async for run_event in agent.arun(
        "Fetch the top 2 hackernews stories", stream=True
    ):
        if run_event.is_paused:
            for requirement in run_event.active_requirements:
                if requirement.needs_confirmation:
                    # Ask for confirmation
                    console.print(
                        f"Tool name [bold blue]{requirement.tool_execution.tool_name}({requirement.tool_execution.tool_args})[/] requires confirmation."
                    )
                    message = (
                        Prompt.ask(
                            "Do you want to continue?", choices=["y", "n"], default="y"
                        )
                        .strip()
                        .lower()
                    )

                    if message == "n":
                        requirement.reject()
                    else:
                        requirement.confirm()

            async for resp in agent.acontinue_run(  # type: ignore
                run_id=run_event.run_id, updated_tools=run_event.tools, stream=True
            ):
                print(resp.content, end="")

    # Or for simple debug flow
    # await agent.aprint_response("Fetch the top 2 hackernews stories", stream=True)


if __name__ == "__main__":
    asyncio.run(main())

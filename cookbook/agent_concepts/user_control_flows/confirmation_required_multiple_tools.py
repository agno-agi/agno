"""🤝 Human-in-the-Loop: Adding User Confirmation to Tool Calls

This example shows how to implement human-in-the-loop functionality in your Agno tools.

In this case we have multiple tools and only one of them requires confirmation.

The agent should execute the tool that doesn't require confirmation and then pause for user confirmation.

The user can then either approve or reject the tool call and the agent should continue from where it left off.
"""

import json

import httpx
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools import tool
from agno.utils import pprint


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


@tool(requires_confirmation=True)
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email.

    Args:
        to (str): Email address to send to
        subject (str): Subject of the email
        body (str): Body of the email
    """
    return f"Email sent to {to} with subject {subject} and body {body}"


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[get_top_hackernews_stories, send_email],
    markdown=True,
)

run_response = agent.run(
    "Fetch the top 2 hackernews stories and email them to john@doe.com."
)
if run_response.is_paused:  # Or agent.run_response.is_paused
    for tool in run_response.tools:
        if tool.requires_confirmation:
            print(f"Tool name {tool.tool_name} requires confirmation.")
            print("Tool args: ", tool.tool_args)
            user_input = input("Do you want to proceed? (y/n) ")
            # We update the tools in place
            tool.confirmed = user_input == "y"
        else:
            print(
                f"Tool name {tool.tool_name} was completed in {tool.metrics.time:.2f} seconds."
            )

    run_response = agent.continue_run()
    pprint.pprint_run_response(run_response)

# Or for simple debug flow
# agent.print_response("Fetch the top 2 hackernews stories")

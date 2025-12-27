"""
This example demonstrates how to use tool hooks with teams and agents.

Tool hooks allow you to intercept and monitor tool function calls, providing
logging, timing, and other observability features.
"""

import time
from typing import Any, Callable, Dict
from uuid import uuid4

from agno.agent.agent import Agent
from agno.models.anthropic.claude import Claude
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reddit import RedditTools
from agno.utils.log import logger


def logger_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
    """
    Tool hook that logs function calls and measures execution time.

    Args:
        function_name: Name of the function being called
        function_call: The actual function to call
        arguments: Arguments passed to the function

    Returns:
        The result of the function call
    """
    if function_name == "delegate_task_to_member":
        member_id = arguments.get("member_id")
        logger.info(f"Delegating task to member {member_id}")

    # Start timer
    start_time = time.time()
    result = function_call(**arguments)
    # End timer
    end_time = time.time()
    duration = end_time - start_time
    logger.info(f"Function {function_name} took {duration:.2f} seconds to execute")
    return result


# Reddit search agent with tool hooks
reddit_agent = Agent(
    name="Reddit Agent",
    id="reddit-agent",
    role="Search reddit for information",
    tools=[RedditTools(cache_results=True)],
    instructions=[
        "Find information about the company on Reddit",
    ],
    tool_hooks=[logger_hook],
)

# Web search agent with tool hooks
website_agent = Agent(
    name="Website Agent",
    id="website-agent",
    role="Search the website for information",
    model=OpenAIChat(id="o3-mini"),
    tools=[DuckDuckGoTools(cache_results=True)],
    instructions=[
        "Search the website for information",
    ],
    tool_hooks=[logger_hook],
)

# Generate unique user ID
user_id = str(uuid4())

# Create team with tool hooks
company_info_team = Team(
    name="Company Info Team",
    model=Claude(id="claude-3-7-sonnet-latest"),
    members=[
        reddit_agent,
        website_agent,
    ],
    markdown=True,
    instructions=[
        "You are a team that finds information about a company.",
        "First search the web and wikipedia for information about the company.",
        "If you can find the company's website URL, then scrape the homepage and the about page.",
    ],
    show_members_responses=True,
    tool_hooks=[logger_hook],
)

if __name__ == "__main__":
    company_info_team.print_response(
        "Write me a full report on everything you can find about Agno, the company building AI agent infrastructure.",
        stream=True,
    )

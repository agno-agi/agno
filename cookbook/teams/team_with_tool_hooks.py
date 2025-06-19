import time
from typing import Any, Callable, Dict
from uuid import uuid4

from agno.agent.agent import Agent
from agno.models.anthropic.claude import Claude
from agno.models.mistral.mistral import MistralChat
from agno.models.openai.chat import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reddit import RedditTools
from agno.utils.log import logger


def logger_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
    if function_name == "transfer_task_to_member":
        member_id = arguments.get("member_id")
        logger.info(f"Transferring task to member {member_id}")

    # Start timer
    start_time = time.time()
    result = function_call(**arguments)
    # End timer
    end_time = time.time()
    duration = end_time - start_time
    logger.info(f"Function {function_name} took {duration:.2f} seconds to execute")
    return result


reddit_agent = Agent(
    name="Reddit Agent",
    agent_id="reddit-agent",
    role="Search reddit for information",
    model=MistralChat(id="mistral-large-latest"),
    tools=[RedditTools(cache_results=True)],
    instructions=[
        "Find information about the company on Reddit",
    ],
    tool_hooks=[logger_hook],
)

website_agent = Agent(
    name="Website Agent",
    agent_id="website-agent",
    role="Search the website for information",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools(cache_results=True)],
    instructions=[
        "Search the website for information",
    ],
    tool_hooks=[logger_hook],
)

user_id = str(uuid4())

company_info_team = Team(
    name="Company Info Team",
    mode="coordinate",
    user_id=user_id,
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

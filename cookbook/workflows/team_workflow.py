from agno.workflow import Workflow

class TeamWorkflow(Workflow):
    def __init__(self):
        super().__init__()
        self.name = "Team Workflow"
        self.description = "A workflow for a team of agents"
        """Please install dependencies using:
pip install openai newspaper4k lxml_html_clean agno
"""

import json
from textwrap import dedent
from typing import Iterator

import httpx
from agno.agent import Agent, RunResponse
from agno.tools.newspaper4k import Newspaper4kTools
from agno.utils.log import logger
from agno.utils.pprint import pprint_run_response
from agno.workflow import Workflow

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.hackernews import HackerNewsTools
from agno.tools.exa import ExaTools


class HackerNewsReporter(Workflow):
    description: str = (
        "Get the top stories from Hacker News and write a report on them."
    )

   
    reddit_researcher = Agent(
        name="Reddit Researcher",
        role="Research a topic on Reddit",
        model=OpenAIChat(id="gpt-4o"),
        tools=[ExaTools()],
        add_name_to_instructions=True,
        instructions=dedent("""
            You are a Reddit researcher.
            You will be given a topic to research on Reddit.
            You will need to find the most relevant posts on Reddit.
        """),
    )

    hackernews_researcher = Agent(
        name="HackerNews Researcher",
        model=OpenAIChat("gpt-4o"),
        role="Research a topic on HackerNews.",
        tools=[HackerNewsTools()],
        add_name_to_instructions=True,
        instructions=dedent("""
            You are a HackerNews researcher.
            You will be given a topic to research on HackerNews.
            You will need to find the most relevant posts on HackerNews.
        """),
    )


    agent_team = Team(
        name="Discussion Team",
        mode="collaborate",
        model=OpenAIChat("gpt-4o"),
        members=[
            reddit_researcher,
            hackernews_researcher,
        ],
        instructions=[
            "You are a discussion master.",
            "You have to stop the discussion when you think the team has reached a consensus.",
        ],
        success_criteria="The team has reached a consensus.",
        enable_agentic_context=True,
        show_tool_calls=True,
        markdown=True,
        debug_mode=True,
        show_members_responses=True,
    )

    writer: Agent = Agent(
        tools=[Newspaper4kTools()],
        description="Write an engaging report on the top stories from hackernews.",
        instructions=[
            "You will be provided with top stories and their links.",
            "Carefully read each article and think about the contents",
            "Then generate a final New York Times worthy article",
            "Break the article into sections and provide key takeaways at the end.",
            "Make sure the title is catchy and engaging.",
            "Share score, title, url and summary of every article.",
            "Give the section relevant titles and provide details/facts/processes in each section.",
            "Ignore articles that you cannot read or understand.",
            "REMEMBER: you are writing for the New York Times, so the quality of the article is important.",
        ],
    )

    def get_top_hackernews_stories(self, num_stories: int = 10) -> str:
        """Use this function to get top stories from Hacker News.

        Args:
            num_stories (int): Number of stories to return. Defaults to 10.

        Returns:
            str: JSON string of top stories.
        """


    def run(self) -> Iterator[RunResponse]:
       
        logger.info(f"Getting top stories from HackerNews.")
        discussion: RunResponse = self.agent_team.run('Getting 2 top stories from HackerNews and reddit and write a brief report on them')
        if discussion is None or not discussion.content:
            yield RunResponse(
                run_id=self.run_id, content="Sorry, could not get the top stories."
            )
            return

        logger.info("Reading each story and writing a report.")
        yield from self.writer.run(discussion.content, stream=True)


if __name__ == "__main__":
    # Run workflow
    report: Iterator[RunResponse] = HackerNewsReporter(debug_mode=False).run(
    )
    # Print the report
    pprint_run_response(report, markdown=True, show_time=True)

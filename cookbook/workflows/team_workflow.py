from textwrap import dedent
from typing import Iterator

from agno.agent import Agent, RunResponse
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunResponse
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.hackernews import HackerNewsTools
from agno.tools.newspaper4k import Newspaper4kTools
from agno.utils.log import logger
from agno.utils.pprint import pprint_run_response
from agno.workflow import Workflow


class TeamWorkflow(Workflow):
    description: str = (
        "Get the top stories from Hacker News and Reddit and write a report on them."
    )

    reddit_researcher = Agent(
        name="Reddit Researcher",
        role="Research a topic on Reddit",
        model=OpenAIChat(id="gpt-4o"),
        tools=[DuckDuckGoTools(cache_results=True)],
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
            "You are a discussion coordinator.",
            "Your primary role is to facilitate the research process.",
            "Once both team members have provided their research results with links to top stories from their respective platforms (Reddit and HackerNews), you should stop the discussion.",
            "Do not continue the discussion after receiving the links - your goal is to collect the research results, not to reach a consensus on content.",
            "Ensure each member provides relevant links with brief descriptions before concluding.",
        ],
        success_criteria="The team has reached a consensus.",
        enable_agentic_context=True,
        show_tool_calls=True,
        markdown=True,
        debug_mode=True,
        show_members_responses=True,
    )

    writer: Agent = Agent(
        tools=[Newspaper4kTools(), ExaTools()],
        description="Write an engaging report on the top stories from various sources.",
        instructions=[
            "You will receive links to top stories from Reddit and HackerNews from the agent team.",
            "Your task is to access these links and thoroughly read each article.",
            "Extract key information, insights, and notable points from each source.",
            "Write a comprehensive, well-structured report that synthesizes the information.",
            "Create a catchy and engaging title for your report.",
            "Organize the content into relevant sections with descriptive headings.",
            "For each article, include its source, title, URL, and a brief summary.",
            "Provide detailed analysis and context for the most important stories.",
            "End with key takeaways that summarize the main insights.",
            "Maintain a professional tone similar to New York Times reporting.",
            "If you cannot access or understand certain articles, note this and focus on the ones you can analyze.",
        ],
    )

    def run(self) -> Iterator[RunResponse]:
        logger.info("Getting top stories from HackerNews.")
        discussion: TeamRunResponse = self.agent_team.run(
            "Getting 2 top stories from HackerNews and reddit and write a brief report on them"
        )
        if discussion is None or not discussion.content:
            yield RunResponse(
                run_id=self.run_id, content="Sorry, could not get the top stories."
            )
            return

        logger.info("Reading each story and writing a report.")
        yield from self.writer.run(discussion.content, stream=True)


if __name__ == "__main__":
    # Run workflow
    report: Iterator[RunResponse] = TeamWorkflow(debug_mode=False).run()
    # Print the report
    pprint_run_response(report, markdown=True, show_time=True)

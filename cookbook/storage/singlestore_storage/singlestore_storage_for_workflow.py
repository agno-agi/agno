import json
import os
from os import getenv
from typing import Iterator

import httpx
from agno.agent import Agent
from agno.run.response import RunResponse
from agno.storage.singlestore import SingleStoreStorage
from agno.tools.newspaper4k import Newspaper4kTools
from agno.utils.certs import download_cert
from agno.utils.log import logger
from agno.utils.pprint import pprint_run_response
from agno.workflow import Workflow
from sqlalchemy.engine import create_engine


class HackerNewsReporter(Workflow):
    description: str = (
        "Get the top stories from Hacker News and write a report on them."
    )

    hn_agent: Agent = Agent(
        description="Get the top stories from hackernews. "
        "Share all possible information, including url, score, title and summary if available.",
        show_tool_calls=True,
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
            "Give the section relevant titles and provide details/facts/processes in each section."
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

        # Fetch top story IDs
        response = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json")
        story_ids = response.json()

        # Fetch story details
        stories = []
        for story_id in story_ids[:num_stories]:
            story_response = httpx.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
            )
            story = story_response.json()
            story["username"] = story["by"]
            stories.append(story)
        return json.dumps(stories)

    def run(self, num_stories: int = 5) -> Iterator[RunResponse]:
        # Set the tools for hn_agent here to avoid circular reference
        self.hn_agent.tools = [self.get_top_hackernews_stories]

        logger.info(f"Getting top {num_stories} stories from HackerNews.")
        top_stories: RunResponse = self.hn_agent.run(num_stories=num_stories)
        if top_stories is None or not top_stories.content:
            yield RunResponse(
                run_id=self.run_id, content="Sorry, could not get the top stories."
            )
            return

        logger.info("Reading each story and writing a report.")
        yield from self.writer.run(top_stories.content, stream=True)


if __name__ == "__main__":
    USERNAME = getenv("SINGLESTORE_USERNAME")
    PASSWORD = getenv("SINGLESTORE_PASSWORD")
    HOST = getenv("SINGLESTORE_HOST")
    PORT = getenv("SINGLESTORE_PORT")
    DATABASE = getenv("SINGLESTORE_DATABASE")
    SSL_CERT = getenv("SINGLESTORE_SSL_CERT", None)

    # Download the certificate if SSL_CERT is not provided
    if not SSL_CERT:
        SSL_CERT = download_cert(
            cert_url="https://portal.singlestore.com/static/ca/singlestore_bundle.pem",
            filename="singlestore_bundle.pem",
        )
        if SSL_CERT:
            os.environ["SINGLESTORE_SSL_CERT"] = SSL_CERT

    # SingleStore DB URL
    db_url = f"mysql+pymysql://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}?charset=utf8mb4"
    if SSL_CERT:
        db_url += f"&ssl_ca={SSL_CERT}&ssl_verify_cert=true"

    # Create a DB engine
    db_engine = create_engine(db_url)
    # Run workflow
    report: Iterator[RunResponse] = HackerNewsReporter(
        storage=SingleStoreStorage(
            table_name="workflow_sessions",
            mode="workflow",
            db_engine=db_engine,
            schema=DATABASE,
        ),
        debug_mode=False,
    ).run(num_stories=5)
    # Print the report
    pprint_run_response(report, markdown=True, show_time=True)

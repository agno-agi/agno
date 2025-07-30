"""Please install dependencies using:
pip install openai newspaper4k lxml_html_clean agno httpx
"""

import json
from typing import AsyncIterator

import httpx
from agno.agent import Agent, RunResponse
from agno.run.workflow import WorkflowCompletedEvent
from agno.tools.newspaper4k import Newspaper4kTools
from agno.utils.log import logger
from agno.utils.pprint import pprint_run_response
from agno.workflow import Workflow


class AsyncHackerNewsReporter(Workflow):
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

    async def get_top_hackernews_stories(self, num_stories: int = 10) -> str:
        """Use this function to get top stories from Hacker News.

        Args:
            num_stories (int): Number of stories to return. Defaults to 10.

        Returns:
            str: JSON string of top stories.
        """
        async with httpx.AsyncClient() as client:
            # Fetch top story IDs
            response = await client.get(
                "https://hacker-news.firebaseio.com/v0/topstories.json"
            )
            story_ids = response.json()

            # Fetch story details concurrently
            tasks = [
                client.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                )
                for story_id in story_ids[:num_stories]
            ]
            responses = await asyncio.gather(*tasks)

            stories = []
            for response in responses:
                story = response.json()
                story["username"] = story["by"]
                stories.append(story)

            return json.dumps(stories)

    async def arun(self, num_stories: int = 5) -> AsyncIterator[RunResponse]:
        # Set the tools for hn_agent here to avoid circular reference
        self.hn_agent.tools = [self.get_top_hackernews_stories]

        logger.info(f"Getting top {num_stories} stories from HackerNews.")
        top_stories: RunResponse = await self.hn_agent.arun(num_stories=num_stories)
        if top_stories is None or not top_stories.content:
            yield WorkflowCompletedEvent(
                run_id=self.run_id,
                content="Sorry, could not get the top stories.",
            )
            return

        logger.info("Reading each story and writing a report.")
        # Get the async iterator from writer.arun()
        writer_response = await self.writer.arun(top_stories.content, stream=True)

        # Stream the writer's response directly
        async for response in writer_response:
            if response.content:
                response.run_id = self.run_id
                yield response


if __name__ == "__main__":
    import asyncio

    async def main():
        # Initialize the workflow
        workflow = AsyncHackerNewsReporter(debug_mode=False)

        # Run the workflow and collect the final response
        final_content = []
        try:
            async for response in workflow.arun(num_stories=5):
                if response.content:
                    final_content.append(response.content)
        except Exception as e:
            import traceback

            traceback.print_exc()
            logger.error(f"Error running workflow: {e}")
            return

        # Create final response with combined content
        if final_content:
            final_response = RunResponse(content="".join(final_content))
            # Pretty print the final response
            pprint_run_response(final_response, markdown=True, show_time=True)

    # Run the async main function
    asyncio.run(main())

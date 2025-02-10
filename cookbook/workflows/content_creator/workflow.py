import json
from typing import List, Optional

from agno.agent import Agent, RunResponse
from agno.models.openai import OpenAIChat
from agno.run.response import RunEvent
from agno.tools.firecrawl import FirecrawlTools
from agno.utils.log import logger
from agno.workflow import Workflow
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from cookbook.workflows.content_creator_workflow.config import PostType
from cookbook.workflows.content_creator_workflow.prompts import (
    agents_config,
    tasks_config,
)
from cookbook.workflows.content_creator_workflow.scheduler import schedule

# Load environment variables
load_dotenv()


# Define Pydantic models to structure responses
class BlogAnalyzer(BaseModel):
    """
    Represents the response from the Blog Analyzer agent.
    Includes the blog title and content in Markdown format.
    """

    title: str
    blog_content_markdown: str


class Tweet(BaseModel):
    """
    Represents an individual tweet within a Twitter thread.
    """

    content: str
    is_hook: bool = Field(
        default=False, description="Marks if this tweet is the 'hook' (first tweet)"
    )
    media_urls: Optional[List[str]] = Field(
        default_factory=list, description="Associated media URLs, if any"
    )  # type: ignore


class Thread(BaseModel):
    """
    Represents a complete Twitter thread containing multiple tweets.
    """

    topic: str
    tweets: List[Tweet]


class LinkedInPost(BaseModel):
    """
    Represents a LinkedIn post.
    """

    content: str
    media_url: Optional[List[str]] = None  # Optional media attachment URL


class ContentPlanningWorkflow(Workflow):
    """
    This workflow automates the process of:
    1. Scraping a blog post using the Blog Analyzer agent.
    2. Generating a content plan for either Twitter or LinkedIn based on the scraped content.
    3. Scheduling and publishing the planned content.
    """

    # This description is used only in workflow UI
    description: str = (
        "Plan, schedule, and publish social media content based on a blog post."
    )

    # Blog Analyzer Agent: Extracts blog content (title, sections) and converts it into Markdown format for further use.
    blog_analyzer: Agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[
            FirecrawlTools(scrape=True, crawl=False)
        ],  # Enables blog scraping capabilities
        description=f"{agents_config['blog_analyzer']['role']} - {agents_config['blog_analyzer']['goal']}",
        instructions=[
            f"{agents_config['blog_analyzer']['backstory']}",
            tasks_config["analyze_blog"][
                "description"
            ],  # Task-specific instructions for blog analysis
        ],
        response_model=BlogAnalyzer,  # Expects response to follow the BlogAnalyzer Pydantic model
    )

    # Twitter Thread Planner: Creates a Twitter thread from the blog content, each tweet is concise, engaging,
    # and logically connected with relevant media.
    twitter_thread_planner: Agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        description=f"{agents_config['twitter_thread_planner']['role']} - {agents_config['twitter_thread_planner']['goal']}",
        instructions=[
            f"{agents_config['twitter_thread_planner']['backstory']}",
            tasks_config["create_twitter_thread_plan"]["description"],
        ],
        response_model=Thread,  # Expects response to follow the Thread Pydantic model
    )

    # LinkedIn Post Planner: Converts blog content into a structured LinkedIn post, optimized for a professional
    # audience with relevant hashtags.
    linkedin_post_planner: Agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        description=f"{agents_config['linkedin_post_planner']['role']} - {agents_config['linkedin_post_planner']['goal']}",
        instructions=[
            f"{agents_config['linkedin_post_planner']['backstory']}",
            tasks_config["create_linkedin_post_plan"]["description"],
        ],
        response_model=LinkedInPost,  # Expects response to follow the LinkedInPost Pydantic model
    )

    def scrape_blog_post(self, blog_post_url: str, use_cache: bool = True):
        if use_cache and blog_post_url in self.session_state:
            logger.info(f"Using cache for blog post: {blog_post_url}")
            return self.session_state[blog_post_url]
        else:
            response: RunResponse = self.blog_analyzer.run(blog_post_url)
            if isinstance(response.content, BlogAnalyzer):
                result = response.content
                logger.info(f"Blog title: {result.title}")
                self.session_state[blog_post_url] = result.blog_content_markdown
                return result.blog_content_markdown
            else:
                raise ValueError("Unexpected content type received from blog analyzer.")

    def generate_plan(self, blog_content: str, post_type: PostType):
        plan_response: RunResponse = RunResponse(content=None)
        if post_type == PostType.TWITTER:
            logger.info(f"Generating post plan for {post_type}")
            plan_response = self.twitter_thread_planner.run(blog_content)
        elif post_type == PostType.LINKEDIN:
            logger.info(f"Generating post plan for {post_type}")
            plan_response = self.linkedin_post_planner.run(blog_content)
        else:
            raise ValueError(f"Unsupported post type: {post_type}")

        if isinstance(plan_response.content, (Thread, LinkedInPost)):
            return plan_response.content
        elif isinstance(plan_response.content, str):
            data = json.loads(plan_response.content)
            if post_type == PostType.TWITTER:
                return Thread(**data)
            else:
                return LinkedInPost(**data)
        else:
            raise ValueError("Unexpected content type received from planner.")

    def schedule_and_publish(self, plan, post_type: PostType) -> RunResponse:
        """
        Schedules and publishes the content leveraging Typefully api.
        """
        logger.info(f"# Publishing content for post type: {post_type}")

        # Use the `scheduler` module directly to schedule the content
        response = schedule(
            thread_model=plan,
            post_type=post_type,  # Either "Twitter" or "LinkedIn"
        )

        logger.info(f"Response: {response}")

        if response:
            return RunResponse(content=response, event=RunEvent.workflow_completed)
        else:
            return RunResponse(
                content="Failed to schedule content.", event=RunEvent.workflow_completed
            )

    def run(self, blog_post_url, post_type) -> RunResponse:
        """
        Args:
            blog_post_url: URL of the blog post to analyze.
            post_type: Type of post to generate (e.g., Twitter or LinkedIn).
        """
        # Scrape the blog post
        blog_content = self.scrape_blog_post(blog_post_url)

        # Generate the plan based on the blog and post type
        plan = self.generate_plan(blog_content, post_type)

        # Schedule and publish the content
        response = self.schedule_and_publish(plan, post_type)

        return response


if __name__ == "__main__":
    # Initialize and run the workflow
    blogpost_url = "https://blog.dailydoseofds.com/p/5-chunking-strategies-for-rag"
    workflow = ContentPlanningWorkflow()
    post_response = workflow.run(
        blog_post_url=blogpost_url, post_type=PostType.TWITTER
    )  # PostType.LINKEDIN for LinkedIn post
    logger.info(post_response.content)

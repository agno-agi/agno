from textwrap import dedent
from typing import Dict, List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.firecrawl import FirecrawlTools
from pydantic import BaseModel, Field
from rich.pretty import pprint


class ContentSection(BaseModel):
    """Represents a section of content from the webpage."""

    heading: Optional[str] = Field(None, description="Section heading")
    content: str = Field(..., description="Section content text")


class PageInformation(BaseModel):
    """Structured representation of a webpage."""

    url: str = Field(..., description="URL of the page")
    title: str = Field(..., description="Title of the page")
    description: Optional[str] = Field(
        None, description="Meta description or summary of the page"
    )
    features: Optional[List[str]] = Field(None, description="Key feature list")
    content_sections: Optional[List[ContentSection]] = Field(
        None, description="Main content sections of the page"
    )
    links: Optional[Dict[str, str]] = Field(
        None, description="Important links found on the page with description"
    )
    contact_info: Optional[Dict[str, str]] = Field(
        None, description="Contact information if available"
    )
    metadata: Optional[Dict[str, str]] = Field(
        None, description="Important metadata from the page"
    )


agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    tools=[FirecrawlTools(enable_scrape=True, enable_crawl=True)],
    instructions=dedent("""
        You are an expert web researcher and content extractor. Extract comprehensive, structured information
        from the provided webpage. Focus on:

        1. Accurately capturing the page title, description, and key features
        2. Identifying and extracting main content sections with their headings
        3. Finding important links to related pages or resources
        4. Locating contact information if available
        5. Extracting relevant metadata that provides context about the site

        Be thorough but concise. If the page has extensive content, prioritize the most important information.
    """).strip(),
    output_schema=PageInformation,
)

result = agent.run("Extract all information from https://www.agno.com")
pprint(result.content)

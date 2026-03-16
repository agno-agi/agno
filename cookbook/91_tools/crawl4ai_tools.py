"""
Crawl4AI Tools - Web Scraping and Content Extraction

This example demonstrates how to use Crawl4aiTools for web crawling and content extraction.
Crawl4aiTools has a single enable_ flag: enable_crawl.

Run: `uv pip install crawl4ai` to install the dependencies
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.crawl4ai import Crawl4aiTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Example 1: All functions enabled with pruning (default behavior)
agent_full = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        Crawl4aiTools(use_pruning=True)
    ],  # All functions enabled with content pruning
    description="You are a comprehensive web research assistant with all crawling capabilities.",
    instructions=[
        "Use Crawl4AI tools to extract information from web pages",
        "Provide detailed summaries and analysis of web content",
        "Handle various content types including articles, documentation, and repositories",
        "Use content pruning to focus on main content and reduce noise",
    ],
    markdown=True,
)

# Example 2: Enable specific crawling functions
agent_basic = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        Crawl4aiTools(
            use_pruning=True,
            enable_crawl=True,
        )
    ],
    description="You are a basic web content extractor focused on page content only.",
    instructions=[
        "Extract and summarize main content from web pages",
        "Focus on text content analysis and summarization",
        "Provide clean, well-structured content summaries",
    ],
    markdown=True,
)

# Example 3: Without pruning
agent_raw = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[Crawl4aiTools(use_pruning=False)],
    description="You are a web intelligence agent that captures full page content.",
    instructions=[
        "Perform comprehensive web analysis using Crawl4AI",
        "Capture full page content without pruning",
        "Provide detailed insights about web pages",
    ],
    markdown=True,
)

# Example usage

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Comprehensive Web Analysis Example ===")
    agent_full.print_response(
        "Give me a detailed summary of the Agno project from https://github.com/agno-agi/agno and what are its main features?"
    )

    print("\n=== Basic Content Extraction Example ===")
    agent_basic.print_response(
        "Extract the main content and history from https://en.wikipedia.org/wiki/Python_(programming_language)"
    )

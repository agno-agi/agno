"""
Crawl4AI Tools - Web Scraping and Content Extraction

This example demonstrates how to use Crawl4aiTools for web crawling and content extraction.
Shows enable_ flag patterns for selective function access.
Crawl4aiTools is a small tool (<6 functions) so it uses enable_ flags.

Run: `pip install crawl4ai` to install the dependencies
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.crawl4ai import Crawl4aiTools

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
            enable_crawl_page=True,
            enable_extract_content=True,
            enable_extract_links=False,  # Disable link extraction
            enable_take_screenshot=False,  # Disable screenshot functionality
        )
    ],
    description="You are a basic web content extractor focused on page content only.",
    instructions=[
        "Extract and summarize main content from web pages",
        "Cannot extract links or take screenshots",
        "Focus on text content analysis and summarization",
        "Provide clean, well-structured content summaries",
    ],
    markdown=True,
)

# Example 3: Enable all functions using 'all=True' pattern
agent_comprehensive = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[Crawl4aiTools(use_pruning=True, all=True)],
    description="You are a full-featured web intelligence agent with all crawling capabilities.",
    instructions=[
        "Perform comprehensive web analysis using all Crawl4AI features",
        "Extract content, links, take screenshots, and analyze page structure",
        "Provide detailed insights about web pages and their relationships",
        "Support advanced web research and content analysis workflows",
    ],
    markdown=True,
)

# Example 4: Screenshot and visual analysis focused
agent_visual = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        Crawl4aiTools(
            use_pruning=False,  # Don't prune for visual analysis
            enable_crawl_page=True,
            enable_take_screenshot=True,
            enable_extract_content=False,  # Focus on visual, not text
            enable_analyze_layout=True,  # Assuming this function exists
        )
    ],
    description="You are a web visual analyst focused on page screenshots and layout analysis.",
    instructions=[
        "Take screenshots of web pages and analyze their visual layout",
        "Cannot extract detailed text content",
        "Focus on visual elements, design, and user interface analysis",
        "Provide insights about web page structure and visual design",
    ],
    markdown=True,
)

# Example usage
print("=== Comprehensive Web Analysis Example ===")
agent_full.print_response(
    "Give me a detailed summary of the Agno project from https://github.com/agno-agi/agno and what are its main features?"
)

print("\n=== Basic Content Extraction Example ===")
agent_basic.print_response(
    "Extract the main content and history from https://en.wikipedia.org/wiki/Python_(programming_language)"
)

print("\n=== Advanced Web Intelligence Example ===")
agent_comprehensive.print_response(
    "Analyze the structure, content, and key links from https://docs.python.org/3/ and provide insights about the documentation organization"
)

# Example 2: Extract main content only (remove navigation, ads, etc.)
# agent_clean = Agent(tools=[Crawl4aiTools(use_pruning=True)])
# agent_clean.print_response(
#     "Get the History from https://en.wikipedia.org/wiki/Python_(programming_language)"
# )

# Example 3: Search for specific content on a page
# agent_search = Agent(
#     instructions="You are a helpful assistant that can crawl the web and extract information. Use have access to crawl4ai tools to extract information from the web.",
#     tools=[Crawl4aiTools()],
# )
# agent_search.print_response(
#     "What are the diferent Techniques used in AI? https://en.wikipedia.org/wiki/Artificial_intelligence"
# )

# Example 4: Multiple URLs with clean extraction
# agent_multi = Agent(
#     tools=[Crawl4aiTools(use_pruning=True, headless=False)]
# )
# agent_multi.print_response(
#     "Compare the main content from https://en.wikipedia.org/wiki/Artificial_intelligence and https://en.wikipedia.org/wiki/Machine_learning"
# )

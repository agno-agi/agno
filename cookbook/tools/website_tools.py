"""
Website Tools - Web Scraping and Content Analysis

This example demonstrates how to use WebsiteTools for web scraping and analysis.
Shows enable_ flag patterns for selective function access.
WebsiteTools is a small tool (<6 functions) so it uses enable_ flags.
"""

from agno.agent import Agent
from agno.tools.website import WebsiteTools

# Example 1: All functions enabled (default behavior)
agent_full = Agent(
    tools=[WebsiteTools()],  # All functions enabled by default
    description="You are a comprehensive web scraping specialist with all website analysis capabilities.",
    instructions=[
        "Help users scrape and analyze website content",
        "Provide detailed summaries and insights from web pages",
        "Handle various website formats and structures", 
        "Ensure respectful scraping practices",
    ],
    markdown=True,
)

# Example 2: Enable specific scraping functions
agent_basic = Agent(
    tools=[WebsiteTools(
        enable_search_page=True,
        enable_extract_content=True,
        enable_extract_links=False,    # Disable link extraction
        enable_analyze_structure=False, # Disable structure analysis
    )],
    description="You are a basic web scraper focused on content extraction only.",
    instructions=[
        "Search and extract main content from web pages",
        "Cannot extract links or perform structural analysis",
        "Focus on clean content extraction and summarization",
        "Provide well-structured content analysis",
    ],
    markdown=True,
)

# Example 3: Enable all functions using 'all=True' pattern
agent_comprehensive = Agent(
    tools=[WebsiteTools(all=True)],
    description="You are a full-featured web intelligence agent with all website analysis capabilities.",
    instructions=[
        "Perform comprehensive website analysis using all available tools",
        "Extract content, analyze structure, and provide detailed insights",
        "Support advanced web research and competitive analysis",
        "Provide actionable recommendations based on website analysis",
    ],
    markdown=True,
)

# Example 4: Read-only web research agent
agent_researcher = Agent(
    tools=[WebsiteTools(
        enable_search_page=True,
        enable_extract_content=True,
        enable_analyze_structure=True,
        enable_modify_content=False,   # Disable any modification capabilities
    )],
    description="You are a web research specialist focused on analyzing existing content.",
    instructions=[
        "Research and analyze web content without modifications",
        "Provide detailed insights about website structure and content",
        "Focus on information gathering and analysis",
        "Support research and competitive intelligence workflows",
    ],
    markdown=True,
)

# Example usage
print("=== Basic Web Content Search Example ===")
agent_basic.print_response(
    "Search web page: 'https://docs.agno.com/introduction' and summarize the key concepts",
    markdown=True
)

print("\n=== Comprehensive Website Analysis Example ===")
agent_comprehensive.print_response(
    "Analyze https://python.org and provide insights about its structure, content, and key features",
    markdown=True,
)

print("\n=== Web Research Example ===")
agent_researcher.print_response(
    "Research the latest developments in AI from https://openai.com and provide a summary",
    markdown=True,
)

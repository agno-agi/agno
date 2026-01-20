"""
Website Tools - Web Scraping and Content Analysis

This example demonstrates how to use WebsiteTools for web scraping and analysis.
Shows enable_ flag patterns for selective function access.
WebsiteTools is a small tool (<6 functions) so it uses enable_ flags.
"""

from agno.agent import Agent
from agno.tools.website import WebsiteTools

agent = Agent(
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

# Example usage
print("=== Basic Web Content Search Example ===")
agent.print_response(
    "Search web page: 'https://docs.agno.com/introduction' and summarize the key concepts",
    markdown=True,
)

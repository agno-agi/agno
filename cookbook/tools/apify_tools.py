from agno.agent import Agent
from agno.tools.apify import ApifyTools

# Apify Tools Demonstration Script
"""
This script showcases the power of web scraping and data extraction using Apify's Actors (serverless tools). 
The Apify ecosystem has 4000+ pre-built Actors for almost any web data extraction need!

---
Configuration Instructions:
1. Install required dependencies:
   pip install agno langchain-apify apify-client

2. Set the APIFY_API_TOKEN environment variable:
   Add a .env file with APIFY_API_TOKEN=your_apify_api_token
---

Tip: Check out the Apify Store (https://apify.com/store) to find tools for almost any web scraping or data extraction task.
"""

# Create an Apify Tools agent with versatile capabilities
agent = Agent(
    name="Web Insights Explorer",
    instructions=[
        "You are a sophisticated web research assistant capable of extracting insights from various online sources. "
        "Use the available tools for your tasks to gather accurate, well-structured information."
    ],
    tools=[
        ApifyTools(
            actors=[
                "apify/rag-web-browser",
                "compass/crawler-google-places",
                "clockworks/free-tiktok-scraper",
            ]
        )
    ],
    markdown=True,
)


def demonstrate_tools():
    print("Apify Tools Exploration 🔍")

    # RAG Web Search Demonstrations
    print("\n1.1 🕵️ RAG Web Search Scenarios:")
    prompt = "Research the latest AI ethics guidelines from top tech companies. Compile a summary from at least 3 different sources comparing their approaches using RAG Web Browser."
    agent.print_response(prompt, show_full_reasoning=True)

    print("\n1.2 🕵️ RAG Web Search Scenarios:")
    prompt = "Carefully extract the key introduction details from https://docs.agno.com/introduction"  #  Extract content from specific website
    agent.print_response(prompt)

    # Google Places Demonstration
    print("\n2. Google Places Crawler:")
    prompt = "Find the top 5 highest-rated coffee shops in San Francisco with detailed information about each location"
    agent.print_response(prompt)

    # Tiktok Scraper Demonstration
    print("\n3. Tiktok Profile Analysis:")
    prompt = "Analyze two profiles on Tiktok that lately added #AI (hashtag AI), extracting their statistics and recent content trends"
    agent.print_response(prompt)


if __name__ == "__main__":
    demonstrate_tools()

"""
Want to add a new tool? It's easy!
- Browse Apify Store
- Find an Actor that matches your needs
- Add a new method to ApifyTools following the existing pattern
- Register the method in the __init__

Examples of potential tools:
- YouTube video info scraper
- Twitter/X profile analyzer
- Product price trackers
- Job board crawlers
- News article extractors
- And SO MUCH MORE!
"""

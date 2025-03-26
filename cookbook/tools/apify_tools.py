from agno.agent import Agent
from agno.tools.apify import ApifyTools

# Apify Tools Demonstration Script
"""
This script showcases the incredible power of web scraping and data extraction 
using Apify's versatile tools. The Apify ecosystem has 4000+ pre-built actors 
for almost any web data extraction need!

---
Configuration Instructions:
To ensure your Apify tools work correctly, you need to set the APIFY_TOKEN environment variable. 
For example add a .env file with APIFY_TOKEN=your_apify_api_key
---

🚀 Pro Tip: Explore the Apify Store (https://apify.com/store) to find tools 
for virtually ANY web scraping or data extraction task you can imagine!
"""

# Create an Apify Tools agent with versatile capabilities
agent = Agent(
    name="Web Insights Explorer",
    instructions=[
        "You are a sophisticated web research assistant capable of extracting insights from various online sources. "
        "Use the available tools for your tasks to gather accurate, well-structured information."
    ],
    tools=[ApifyTools()],
    show_tool_calls=True,
    markdown=True
)

def demonstrate_tools():
    print("Apify Tools Exploration 🔍")
    
    # RAG Web Search Demonstrations
    print("\n1.1 🕵️ RAG Web Search Scenarios:")
    prompt = "Research the latest AI ethics guidelines from top tech companies. Compile a summary from at least 3 different sources comparing their approaches using RAG Web Browser."
    agent.print_response(prompt)
    
    print("\n1.2 🕵️ RAG Web Search Scenarios:")
    prompt = "Carefully extract the key introduction details from https://docs.agno.com/introduction" #  Extract content from specific website
    agent.print_response(prompt)

    # Google Places Demonstration
    print("\n2. Google Places Crawler:")
    prompt = "Find the top 5 highest-rated coffee shops in San Francisco with detailed information about each location"
    agent.print_response(prompt)
    
    # Instagram Scraper Demonstration
    print("\n3. Instagram Profile Analysis:")
    prompt = "Analyze the profile of a popular tech influencer, extracting key follower statistics and recent content trends"
    agent.print_response(prompt)
    
    # Website Content Crawler
    print("\n4. Website Content Extraction:")
    prompt = "Extract the main content and key sections from https://docs.agno.com/introduction/playground"
    agent.tools = [ApifyTools(use_website_content_crawler=True, use_rag_web_search=False)] # Temporarily disable RAG Web Search and enable only Website Content Crawler
    agent.print_response(prompt)

if __name__ == "__main__":
    demonstrate_tools()
    
"""
Want to add a new tool? It's easy!
- Browse Apify Store
- Find an actor that matches your needs
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
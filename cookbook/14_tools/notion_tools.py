from agno.agent import Agent
from agno.tools.notion import NotionTools

# Notion Tools Demonstration Script
"""
This script showcases the power of organizing and managing content in Notion using AI.
Automatically categorize, store, and retrieve information from your Notion workspace!

---
Configuration Instructions:
1. Install required dependencies:
   pip install agno notion-client

2. Create a Notion Integration:
   - Go to https://www.notion.so/my-integrations
   - Click "+ New integration"
   - Name it (e.g., "Agno Agent")
   - Copy the "Internal Integration Token"

3. Create a Notion Database:
   - Create a new page in Notion
   - Add a database (type /database)
   - Add these properties:
     * Name (Title) - already exists
     * Tag (Select) - add options: travel, tech, general-blogs, fashion, documents

4. Share the database with your integration:
   - Open the database page
   - Click "..." → "Add connections"
   - Select your integration

5. Get the database ID from the URL:
   https://www.notion.so/../DATABASE_ID?v=...

6. Set environment variables in .env:
   NOTION_API_KEY=secret_your_integration_token
   NOTION_DATABASE_ID=your_database_id_here
---

Use Cases:
- Personal knowledge management
- Content organization
- Research notes
- Travel planning
- Reading lists
- And much more!
"""

# Create an agent with Notion Tools
notion_agent = Agent(
    name="Notion Knowledge Manager",
    instructions=[
        "You are a smart assistant that helps organize information in Notion.",
        "When given content, analyze it and categorize it appropriately.",
        "Available categories: travel, tech, general-blogs, fashion, documents",
        "Always search first to avoid duplicate pages with the same tag.",
        "Be concise and helpful in your responses.",
    ],
    tools=[NotionTools()],
    markdown=True,
)


def demonstrate_tools():
    print("  Notion Tools Demonstration\n")
    print("=" * 60)

    # Example 1: Travel Notes
    print("\n Example 1: Organizing Travel Information")
    print("-" * 60)
    prompt = """
    I found this amazing travel guide: 
    'Ha Giang Loop in Vietnam - 4 day motorcycle adventure through stunning mountains.
    Best time to visit: October to March. Must-see spots include Ma Pi Leng Pass.'
    
    Save this to Notion under the travel category.
    """
    notion_agent.print_response(prompt)

    # Example 2: Tech Bookmarks
    print("\n Example 2: Saving Tech Articles")
    print("-" * 60)
    prompt = """
    Save this tech article to Notion:
    'The Rise of AI Agents in 2025 - How autonomous agents are revolutionizing software development.
    Key trends include multi-agent systems, agentic workflows, and AI-powered automation.'
    
    Categorize this appropriately and add to Notion.
    """
    notion_agent.print_response(prompt)

    # Example 3: Multiple Items
    print("\n Example 3: Batch Processing Multiple Items")
    print("-" * 60)
    prompt = """
    I need to save these items to Notion:
    1. 'Best fashion trends for spring 2025 - Sustainable fabrics and minimalist designs'
    2. 'My updated resume and cover letter for job applications'
    3. 'Quick thoughts on productivity hacks for remote work'
    
    Process each one and save them to the appropriate categories.
    """
    notion_agent.print_response(prompt)

    # Example 4: Search and Update
    print("\n🔍 Example 4: Finding and Updating Existing Content")
    print("-" * 60)
    prompt = """
    Search for any pages tagged 'tech' and let me know what you find.
    Then add this new insight to one of them:
    'Update: AI agents now support structured output with Pydantic models for better type safety.'
    """
    notion_agent.print_response(prompt)

    # Example 5: Smart Categorization
    print("\n Example 5: Automatic Smart Categorization")
    print("-" * 60)
    prompt = """
    I have this content but I'm not sure where it belongs:
    'Exploring the ancient temples of Angkor Wat in Cambodia. The sunrise view from Angkor Wat 
    is breathtaking. Best visited during the dry season from November to March.'
    
    Analyze this content, decide the best category, and save it to Notion.
    """
    notion_agent.print_response(prompt)

    print("\n" + "=" * 60)
    print(
        "\nYour Notion database now contains organized content across different categories."
    )
    print("Check your Notion workspace to see the results!")


if __name__ == "__main__":
    demonstrate_tools()

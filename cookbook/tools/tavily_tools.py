from agno.agent import Agent
from agno.tools.tavily import TavilyTools

# Example 1: default TavilyTools
agent = Agent(tools=[TavilyTools()])

# Example 2: Enable all Tavily functions (search + extract)
agent_all = Agent(tools=[TavilyTools(all=True)])

# Example 3: Use advanced search with context
context_agent = Agent(
    tools=[
        TavilyTools(
            enable_search=True,
        )
    ]
)

# ============================================================================
# EXTRACT EXAMPLES
# ============================================================================

# Example 4: URL content extraction with markdown format
extract_agent = Agent(
    tools=[
        TavilyTools(
            enable_search=False,  # Disable search for this example
            enable_extract=True,
            extract_depth="basic",  # basic = 1 credit/5 URLs
            extract_format="markdown",
        )
    ]
)

# Example 5: Advanced extraction with images in text format
advanced_extract_agent = Agent(
    tools=[
        TavilyTools(
            enable_search=False,
            enable_extract=True,
            extract_depth="advanced",  # advanced = 2 credits/5 URLs
            extract_format="text",
            include_images=True,
            include_favicon=True,
        )
    ]
)

# Example 6: Combined search and extract
combined_agent = Agent(
    tools=[
        TavilyTools(
            enable_search=True,
            enable_extract=True,
            search_depth="basic",
            extract_depth="basic",
            format="markdown",  # Format for search results
            extract_format="markdown",  # Format for extracted content
        )
    ]
)

# ============================================================================
# TEST THE AGENTS
# ============================================================================

# Test search agents
print("=" * 80)
print("SEARCH EXAMPLES")
print("=" * 80)

agent.print_response(
    "Search for 'language models' and recent developments", markdown=True
)

context_agent.print_response(
    "Get detailed context about artificial intelligence trends", markdown=True
)

# Test extract agents
print("\n" + "=" * 80)
print("EXTRACT EXAMPLES")
print("=" * 80)

extract_agent.print_response(
    "Extract the main content from https://docs.tavily.com/documentation/api-reference/endpoint/extract",
    markdown=True,
)

advanced_extract_agent.print_response(
    "Extract content with images from https://github.com/anthropics/anthropic-sdk-python",
    markdown=True,
)

# Test combined agent
print("\n" + "=" * 80)
print("COMBINED SEARCH & EXTRACT")
print("=" * 80)

combined_agent.print_response(
    "Search for 'Tavily API documentation' and extract content from the most relevant result",
    markdown=True,
)

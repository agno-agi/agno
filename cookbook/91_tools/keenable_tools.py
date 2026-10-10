"""
Keenable Tools
=============================

Demonstrates Keenable web search and page extraction.

Keenable is keyless by default: with no KEENABLE_API_KEY set, these examples run
as-is against the public endpoints. Set KEENABLE_API_KEY to lift rate limits.
"""

from agno.agent import Agent
from agno.tools.keenable import KeenableTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: default KeenableTools — web search, no API key needed
agent = Agent(tools=[KeenableTools()])

# Example 2: with an explicit API key (lifts rate limits)
# agent_keyed = Agent(tools=[KeenableTools(api_key="your-key")])

# Example 3: enable all Keenable functions (search + fetch)
agent_all = Agent(tools=[KeenableTools(all=True)])

# Example 4: JSON output instead of markdown, more results
json_agent = Agent(tools=[KeenableTools(format="json", max_results=10)])

# ============================================================================
# FETCH EXAMPLES
# ============================================================================

# Example 5: page extraction only — read a known URL as clean markdown
fetch_agent = Agent(
    tools=[
        KeenableTools(
            enable_search=False,  # Disable search for this example
            enable_fetch=True,
        )
    ]
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 80)
    print("SEARCH EXAMPLES")
    print("=" * 80)

    agent.print_response(
        "Search for recent developments in small language models", markdown=True
    )

    json_agent.print_response(
        "Find primary sources on the state of open-weight model licensing",
        markdown=True,
    )

    print("\n" + "=" * 80)
    print("FETCH EXAMPLES")
    print("=" * 80)

    fetch_agent.print_response(
        "Read https://docs.agno.com/introduction and summarize what Agno is",
        markdown=True,
    )

    print("\n" + "=" * 80)
    print("COMBINED SEARCH & FETCH")
    print("=" * 80)

    agent_all.print_response(
        "Search for the Agno documentation, then read the most relevant page and "
        "summarize it",
        markdown=True,
    )

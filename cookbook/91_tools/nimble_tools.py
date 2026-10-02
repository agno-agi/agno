from agno.agent import Agent
from agno.tools.nimble import NimbleTools

# ============================================================================
# SEARCH EXAMPLES
# ============================================================================

# Example 1: Basic search with defaults
# The NimbleTools can be configured with global settings like locale and output format
# Search parameters (max_results, deep_search, etc.) are passed in the query
basic_agent = Agent(tools=[NimbleTools()])

# Example 2: Plain text output format
# You can set the output format at initialization for all searches
plaintext_agent = Agent(tools=[NimbleTools(output_format="plain_text")])

# Example 3: Localized search
# Set locale and country for searches in different regions
spanish_agent = Agent(tools=[NimbleTools(locale="es", country="ES")])

# ============================================================================
# TEST THE AGENTS
# ============================================================================

print("=" * 80)
print("EXAMPLE 1: BASIC SEARCH (with default parameters)")
print("=" * 80)
basic_agent.print_response("What are the latest AI developments?", markdown=True)

print("\n" + "=" * 80)
print("EXAMPLE 2: DEEP SEARCH WITH LLM ANSWER")
print("Parameters: max_results=5, deep_search=True, include_answer=True")
print("=" * 80)
# Parameters can be passed when the agent calls the tool
basic_agent.print_response(
    "Compare noise cancelling headphones. "
    "Use max_results=5, deep_search=True, and include_answer=True.",
    markdown=True,
)

print("\n" + "=" * 80)
print("EXAMPLE 3: FAST SEARCH (no deep content)")
print("Parameters: max_results=10, deep_search=False")
print("=" * 80)
basic_agent.print_response(
    "Find recent climate change news. Use max_results=10 and deep_search=False for faster results.",
    markdown=True,
)

print("\n" + "=" * 80)
print("EXAMPLE 4: PLAIN TEXT OUTPUT FORMAT")
print("=" * 80)
plaintext_agent.print_response("What is quantum computing?", markdown=True)

print("\n" + "=" * 80)
print("EXAMPLE 5: TIME-FILTERED SEARCH")
print("Parameters: time_range='day'")
print("=" * 80)
basic_agent.print_response(
    "What happened in tech news today? Use time_range='day' to get only recent results.",
    markdown=True,
)

print("\n" + "=" * 80)
print("EXAMPLE 6: DOMAIN-FILTERED SEARCH")
print("Parameters: include_domains=['github.com', 'stackoverflow.com']")
print("=" * 80)
basic_agent.print_response(
    "Find Python tutorials. Use include_domains=['github.com', 'stackoverflow.com'] to search only those sites.",
    markdown=True,
)

print("\n" + "=" * 80)
print("EXAMPLE 7: LOCALIZED SEARCH (Spanish)")
print("=" * 80)
spanish_agent.print_response("Noticias sobre inteligencia artificial", markdown=True)

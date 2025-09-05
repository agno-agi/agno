from agno.agent import Agent
from agno.tools.pubmed import PubmedTools

# Example 1: Enable all PubMed functions
agent_all = Agent(
    tools=[
        PubmedTools(
            all=True,  # Enable all PubMed search functions
        )
    ],
    markdown=True,
)

# Example 2: Enable specific PubMed functions only
agent_specific = Agent(
    tools=[
        PubmedTools(
            enable_search_pubmed=True,  # Only enable the main search function
        )
    ],
    markdown=True,
)

# Example 3: Default behavior with search enabled
agent = Agent(
    tools=[
        PubmedTools(
            enable_search_pubmed=True,
        )
    ],
    markdown=True,
)

# Example usage with all functions enabled
print("=== Example 1: Using all PubMed functions ===")
agent_all.print_response(
    "Tell me about ulcerative colitis and find the latest research."
)

# Example usage with specific functions only
print("\n=== Example 2: Using specific PubMed functions (search only) ===")
agent_specific.print_response("Search for recent studies on diabetes treatment.")

# Example usage with default configuration
print("\n=== Example 3: Default PubMed agent usage ===")
agent.print_response("Tell me about ulcerative colitis.")

agent.print_response("Find research papers on machine learning in healthcare.")

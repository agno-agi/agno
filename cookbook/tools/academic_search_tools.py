from agno.agent import Agent
from agno.tools.academicsearch import AcademicSearchTools

# Example 1: Basic academic search with default settings
print("=== Example 1: Basic Academic Paper Search ===")
agent = Agent(
    tools=[
        AcademicSearchTools(
            show_results=True,
        )
    ],
    show_tool_calls=True,
    markdown=True,
)

agent.print_response(
    "What are safety mechanisms and mitigation strategies for CRISPR off-target effects?",
    markdown=True,
)

# Example 2: Focused ArXiv search with specific parameters
print("\n=== Example 2: Focused ArXiv Search ===")
agent = Agent(
    tools=[
        AcademicSearchTools(
            max_num_results=5,
            relevance_threshold=0.7,
            show_results=True,
        )
    ],
    show_tool_calls=True,
    markdown=True,
)

# Search for specific content from papers (beyond just abstracts)
agent.print_response(
    "Implementation details of agentic search-enhanced large reasoning models from search-o1",
    markdown=True,
)

# Search for research in specific date range
agent.print_response(
    "Search for novel transformer architecture implementation papers from june 2023 -> jan 2024, focusing on attention mechanisms",
    markdown=True,
)

# Example 3: Medical literature search using PubMed
print("\n=== Example 3: Medical Literature Search ===")
agent.print_response(
    "Find clinical trials and research on COVID-19 vaccine effectiveness in immunocompromised patients",
    markdown=True,
)

# Example 4: Search within a specific famous paper
print("\n=== Example 4: Search Within Specific Paper - Attention Is All You Need ===")
agent.print_response(
    "Search within the paper https://arxiv.org/abs/1706.03762 for details about the multi-head attention mechanism architecture",
    markdown=True,
)

# Example 5: Search within GPT-3 paper for training details
print("\n=== Example 5: Search Within GPT-3 Paper ===")
agent.print_response(
    "Search within the GPT-3 paper https://arxiv.org/abs/2005.14165 for information about the training dataset",
    markdown=True,
)

# Example 6: Search within a recent paper for results
print("\n=== Example 6: Extract Results from Recent Paper ===")
agent.print_response(
    "Search within https://arxiv.org/abs/2303.08774 for the main results",
    markdown=True,
)


# Example 7: Business/Finance academic content
print("\n=== Example 8: Business & Finance Academic Content ===")
business_agent = Agent(
    tools=[
        AcademicSearchTools(
            show_results=True,
        )
    ],
    show_tool_calls=True,
    markdown=True,
)

business_agent.print_response(
    "Explain the concept of risk-free rate from Damodaran's textbook Applied Corporate Finance",
    markdown=True,
)

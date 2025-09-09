"""
This cookbook demonstrates how to use the Valyu Toolkit for academic and web search.

Prerequisites:
- Install: pip install valyu
- Get API key: https://platform.valyu.network
- Set environment variable: export VALYU_API_KEY with your api key or pass the api key while initializing the toolkit
"""

from agno.agent import Agent
from agno.tools.valyu import ValyuTools

agent = Agent(
    tools=[ValyuTools()],
    markdown=True,
)

# Example 1: Basic Academic Paper Search
agent.print_response(
    "What are the latest safety mechanisms and mitigation strategies for CRISPR off-target effects?",
    markdown=True,
)

# Example 2: Focused ArXiv Search with Date Filtering
agent.print_response(
    "Search for transformer architecture papers published between June 2023 and January 2024, focusing on attention mechanisms",
    markdown=True,
)

# Example 3: Search Within Specific Paper
agent.print_response(
    "Search within the paper https://arxiv.org/abs/1706.03762 for details about the multi-head attention mechanism architecture",
    markdown=True,
)

# Example 4: Search Web
agent.print_response(
    "What are the main developments in large language model reasoning capabilities published in 2024?",
    markdown=True,
)

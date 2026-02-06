"""
Valyu Toolkit - Search API for AI Agents

Valyu is a search API providing web search and access to specialised/proprietary data sources:
- Web: Real-time web search with domain filtering
- Life Sciences: PubMed, clinical trials, FDA drug labels, ChEMBL, DrugBank, Open Targets
- Finance: Stock prices, earnings, balance sheets, SEC filings, crypto, forex
- SEC Filings: 10-K, 10-Q, 8-K, proxy statements
- Patents: Global patent database
- Economics: BLS, FRED, World Bank
- Academic Papers: arXiv, PubMed, bioRxiv, medRxiv, Wiley

Prerequisites:
- Install: pip install valyu
- Get API key: https://platform.valyu.network
- Set environment variable: export VALYU_API_KEY=your_api_key
"""

from agno.agent import Agent
from agno.tools.valyu import ValyuTools

# Basic agent with all Valyu search tools
agent = Agent(
    tools=[ValyuTools()],
    markdown=True,
)

# Example 1: General search across all sources
agent.print_response(
    "What are the latest developments in AI safety research?",
    markdown=True,
)

# Example 2: Web search
agent.print_response(
    "Search the web for recent news about OpenAI",
    markdown=True,
)

# Example 3: Life sciences search (biomedical, clinical trials, drugs)
agent.print_response(
    "Find clinical trials for GLP-1 agonists in obesity treatment",
    markdown=True,
)

# Example 4: SEC filings search
agent.print_response(
    "What are the main risk factors in Tesla's latest 10-K filing?",
    markdown=True,
)

# Example 5: Patent search
agent.print_response(
    "Search for patents related to solid-state battery technology",
    markdown=True,
)

# Example 6: Finance search (stocks, earnings, balance sheets)
agent.print_response(
    "Get Apple's quarterly revenue data for 2024",
    markdown=True,
)

# Example 7: Economics search (BLS, FRED, World Bank)
agent.print_response(
    "Find the current US unemployment rate and CPI data",
    markdown=True,
)

# Example 8: Academic paper search
agent.print_response(
    "Search for papers on transformer attention mechanisms from 2024",
    markdown=True,
)


# Advanced: Custom configuration
agent_custom = Agent(
    tools=[
        ValyuTools(
            max_results=5,
            relevance_threshold=0.7,
            text_length=500,
        )
    ],
    markdown=True,
)

agent_custom.print_response(
    "Find the top 5 most relevant papers on CRISPR gene editing",
    markdown=True,
)

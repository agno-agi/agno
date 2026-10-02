"""
AnySearch Tools
=============================

Demonstrates AnySearch tools for web search, batch search, vertical sub-domain
discovery, and full-page extraction.

Requires: OPENAI_API_KEY for the agents' default model, plus optionally
ANYSEARCH_API_KEY. Without an AnySearch key the tools run on AnySearch's anonymous
daily free quota; with one they bill against the paid quota, which comes with
higher concurrency limits. Get a key at https://www.anysearch.com

Any model works here: these agents use the default model, so pass your own - for
example model=DeepSeek(id="deepseek-flash") with DEEPSEEK_API_KEY set.
"""

from agno.agent import Agent
from agno.tools.anysearch import AnySearchTools

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Example 1: Web research
research_agent = Agent(
    tools=[AnySearchTools()],
    description="You are a research assistant that finds current, accurate information.",
    instructions=[
        "Search the web with AnySearch for the question you were asked.",
        "Cite every URL you used.",
        "Call extract on a result when its snippet is too short to answer.",
    ],
)

# Example 2: Vertical search
# get_sub_domains returns the tags and the structured params they need, so the
# agent never guesses a tag or folds structured fields into the query text.
vertical_agent = Agent(
    tools=[AnySearchTools(zone="intl")],
    description="You are an analyst who uses AnySearch's vertical domains.",
    instructions=[
        "Call get_sub_domains first to discover the tag and params a domain expects.",
        "Then call search with that tag and params on every subsequent lookup.",
        "Use batch_search when the question has several independent angles.",
    ],
)

# Example 3: Page reader
# The search tool clips each result's content to content_length_limit characters;
# extract returns the page whole, which is what a reading agent wants.
reader_agent = Agent(
    tools=[
        AnySearchTools(
            enable_search=False, enable_batch_search=False, enable_sub_domains=False
        )
    ],
    description="You are a reading assistant that summarizes pages users point you at.",
    instructions=[
        "Call extract with the URL and summarize what the page actually says."
    ],
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    research_agent.print_response(
        "What are the latest developments in AI agents?",
        markdown=True,
        stream=True,
    )

    vertical_agent.print_response(
        "How did NVDA stock trade this week, and what moved it?",
        markdown=True,
        stream=True,
    )

    reader_agent.print_response(
        "Summarize https://www.anysearch.com/docs/api-endpoints/v1-search",
        markdown=True,
        stream=True,
    )

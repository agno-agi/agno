"""
Sciverse Tools - Scientific Literature Search over Full Text

Sciverse indexes paper metadata and full text, so semantic_search returns citable
passages from paper bodies (not just abstracts) along with the character offset where
each passage lives. Feed that doc_id and offset to read_paper_content to read around it.

SciverseTools is a small tool (<6 functions) so it uses enable_ flags.

Get an API token at https://sciverse.space, then: `export SCIVERSE_API_TOKEN=***`
"""

from agno.agent import Agent
from agno.tools.sciverse import SciverseTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Example 1: Default functions (semantic search, metadata search, full-text reading)
agent_full = Agent(
    tools=[SciverseTools()],
    description="You are a research assistant that answers from primary literature.",
    instructions=[
        "Search for relevant passages before answering",
        "Quote the passage you relied on and name the paper it came from",
        "Read more of the original text when a passage is not enough to answer",
    ],
    markdown=True,
)

# Example 2: Retrieval only, no full-text reading
agent_search_only = Agent(
    tools=[
        SciverseTools(
            enable_semantic_search=True,
            enable_search_papers=True,
            enable_read_paper_content=False,
        )
    ],
    description="You are a literature discovery specialist.",
    instructions=[
        "Find the most relevant papers and passages for the topic",
        "Summarize what each result contributes",
    ],
    markdown=True,
)

# Example 3: Enable all functions, including citation graph traversal
agent_comprehensive = Agent(
    tools=[SciverseTools(all=True)],
    description="You are a comprehensive research assistant for literature reviews.",
    instructions=[
        "Start from semantic search, then follow references to trace a line of work",
        "Distinguish what a paper cites from what cites it",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Question Answering over Full Text ===")
    agent_full.print_response(
        "How do vision transformers handle image patches? Quote the papers you use.",
        markdown=True,
    )

    print("\n=== Structured Literature Discovery ===")
    agent_search_only.print_response(
        "Find papers on CRISPR gene editing published between 2021 and 2023",
        markdown=True,
    )

    print("\n=== Literature Review with Citations ===")
    agent_comprehensive.print_response(
        "Summarize recent work on protein folding prediction and trace what it builds on",
        markdown=True,
    )

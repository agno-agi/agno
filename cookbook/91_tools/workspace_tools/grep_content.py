"""
Workspace — grep_content (regex search)
=======================================

Demonstrates grep_content, which provides regex search with line numbers.
This is the missing piece for code/docs navigation agents.

Unlike search_content (substring, one snippet per file), grep_content returns:
- Every matching line with its line number
- Optional context lines around each match
- Files-only mode for quick discovery

Requires: OPENAI_API_KEY
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.workspace import Workspace

# Point at the agno source code
project_root = Path(__file__).resolve().parents[3]
agno_src = project_root / "libs" / "agno" / "agno"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        Workspace(
            str(agno_src),
            allowed=["read", "list", "search", "grep"],
            confirm=[],
        )
    ],
    markdown=True,
)


if __name__ == "__main__":
    # Demo 1: Find all async def run methods
    print("Demo 1: Find async run methods")
    print("-" * 40)
    agent.print_response(
        "Use grep_content to find all 'async def run' methods in the agent/ directory. "
        "Show the file and line number for each match."
    )

    print("\n")

    # Demo 2: Find class definitions with context
    print("Demo 2: Find Agent class with context")
    print("-" * 40)
    agent.print_response(
        "Use grep_content with context_lines=2 to find where 'class Agent' is defined. "
        "Show the surrounding lines to understand its structure."
    )

    print("\n")

    # Demo 3: Files-only mode for discovery
    print("Demo 3: Files-only discovery")
    print("-" * 40)
    agent.print_response(
        "Use grep_content with files_only=True to find which files contain 'ContextProvider'. "
        "Just list the file names, don't show the content."
    )

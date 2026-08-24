"""
Workspace — grep_content (regex search with line numbers)
=========================================================

grep_content fills the gap between search_content (substring, one snippet per
file) and what code navigation agents need: regex patterns, every matching
line with its line number, and optional context lines.

This example shows a docs-agent pattern: discover files, search with regex,
then read specific sections based on line numbers from grep results.

Requires: OPENAI_API_KEY
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.workspace import Workspace

# Point at the agno libs directory
project_root = Path(__file__).resolve().parents[3]
libs_dir = project_root / "libs" / "agno" / "agno"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        Workspace(
            str(libs_dir),
            allowed=["read", "list", "search", "grep"],
            confirm=[],
        )
    ],
    instructions="""\
You are a code navigation assistant. Use the workspace tools to answer questions:

- list_files: discover what files exist (supports glob patterns, recursive)
- search_content: quick substring search to find which files mention something
- grep_content: regex search with line numbers — use this when you need exact locations
- read_file: read file contents, optionally with line ranges from grep results

When answering questions about code, cite file:line references from grep results.
""",
    markdown=True,
)


if __name__ == "__main__":
    # A practical code navigation task
    agent.print_response(
        "Find all the context providers in this codebase. "
        "Use grep_content to find classes that inherit from ContextProvider, "
        "then summarize what each one does based on its location and name."
    )

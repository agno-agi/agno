"""
Workspace — grep_content (regex search with line numbers)

grep_content is for precise code search: regex patterns, every matching line
with its line number, and optional context lines. Returns JSON with file:line
citations for direct navigation.

This example demonstrates a rename pre-flight sweep — finding all occurrences
of a method name before refactoring.
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.workspace import Workspace

project_root = Path(__file__).resolve().parents[3]
libs_dir = project_root / "libs" / "agno" / "agno"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        Workspace(
            libs_dir,
            allowed=["read", "list", "search", "grep"],
            confirm=[],
        )
    ],
    instructions="""\
You are a refactoring assistant helping prepare a method rename.

Workflow:
1. Use grep_content to find all occurrences with line numbers
2. Use context_lines if you need surrounding code to classify matches
3. Use read_file with a line range when you need more context

Use word-boundary regex (\\b) to avoid false positives. For example,
`\\bsearch_content\\b` matches the sync method but not `asearch_content`.

Cite every finding as file:line so the developer can navigate directly.
""",
    markdown=True,
)


if __name__ == "__main__":
    prompt = """\
We're planning to rename the sync method `search_content` (the async variant
`asearch_content` keeps its name).

1. Search with the word-boundary pattern `\\bsearch_content\\b` and 1 context line
2. Classify each occurrence as: definition, call site, docstring/comment, or test

Note: A plain substring search would falsely include `asearch_content` — that's
why we need the regex word boundary.

Produce a rename checklist with file:line citations.
"""
    print(f"> {prompt}\n")
    agent.print_response(prompt)

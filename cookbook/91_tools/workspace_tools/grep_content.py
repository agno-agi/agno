"""
Workspace — grep_content (regex search with line numbers)
=========================================================

grep_content fills the gap between search_content (substring, one snippet per
file) and what code navigation agents need: regex patterns, every matching
line with its line number, and optional context lines.

This example demonstrates a rename pre-flight sweep — finding all occurrences
of a method name before refactoring. The key insight: substring search would
falsely match `asearch_content` when looking for `search_content`, but the
word-boundary regex `\\bsearch_content\\b` filters precisely.

Features demonstrated:
- `files_only=True`: quick blast-radius check before expensive content search
- `ignore_case=False`: case-sensitive matching (the default)
- `context_lines=1`: see surrounding code to classify each occurrence
- Line numbers: every match is cited as file:line for precise navigation

Workflow:
1. files_only pass → "how big is this refactor?"
2. grep with context → classify: definition, call site, docstring, test
3. read_file with line range → verify specific occurrences

Requires: OPENAI_API_KEY

Prompts to try:
- "Find all TODO comments with grep_content pattern 'TODO|FIXME|HACK'"
- "Search for deprecated warnings using pattern 'warnings\\.warn'"
- "Find exception handlers with pattern 'except[^:]*:' and 2 context lines"
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.workspace import Workspace

# Point at the agno libs directory
project_root = Path(__file__).resolve().parents[3]
libs_dir = project_root / "libs" / "agno" / "agno"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        Workspace(
            str(libs_dir),
            allowed=["read", "list", "search", "grep"],
            confirm=[],
        )
    ],
    instructions="""\
You are a refactoring assistant helping prepare a method rename.

Workflow for rename pre-flight:
1. **Blast radius first.** Use grep_content with files_only=True to list affected
   files before fetching content — this answers "how big is this refactor?"
2. **Grep with context.** Use grep_content with context_lines=1 to see surrounding
   code. Classify each occurrence: definition, call site, docstring, or test.
3. **Verify ambiguous cases.** Use read_file with a line range when you need more
   context than grep provides.

Important: Use word-boundary regex (\\b) to avoid false positives. For example,
`\\bsearch_content\\b` matches the sync method but not `asearch_content`.

Cite every finding as file:line so the developer can navigate directly.
""",
    markdown=True,
)


if __name__ == "__main__":
    # Rename pre-flight: find all search_content occurrences
    # This is a real scenario — agno has both search_content and asearch_content
    prompt = """\
We're planning to rename the sync method `search_content` (the async variant
`asearch_content` keeps its name).

1. First use grep_content with files_only=True to show the blast radius
2. Then search with the word-boundary pattern `\\bsearch_content\\b` and 1 context line
3. Classify each occurrence as: definition, call site, docstring/comment, or test

Note: A plain substring search would falsely include `asearch_content` — that's
why we need the regex word boundary.

Produce a rename checklist with file:line citations.
"""
    print(f"> {prompt}\n")
    agent.print_response(prompt)

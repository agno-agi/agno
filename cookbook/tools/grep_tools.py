"""
GrepTools Example - Search code with grep patterns

Run: `python cookbook/tools/grep_tools.py`

Features:
- grep: Search in a specific file
- grep_recursive: Search recursively across files with pattern matching
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.grep import GrepTools

# Create agent with GrepTools pointing to the agno codebase
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[GrepTools(base_dir="./libs/agno")],
    instructions=[
        "You are a code search assistant.",
        "Use grep to find patterns in the codebase.",
        "Summarize findings clearly.",
    ],
    markdown=True,
)

# Example 1: Search for a pattern recursively in Python files
print("=" * 60)
print("Example 1: Find all TODO comments in Python files")
print("=" * 60)
agent.print_response(
    "Find all TODO comments in Python files. Show me the top findings.",
    stream=True,
)

# Example 2: Search for function definitions
print("\n" + "=" * 60)
print("Example 2: Find class definitions containing 'Tool'")
print("=" * 60)
agent.print_response(
    "Search for class definitions that contain 'Tool' in their name in Python files",
    stream=True,
)

# Example 3: Search in a specific file
print("\n" + "=" * 60)
print("Example 3: Search in a specific file")
print("=" * 60)
agent.print_response(
    "Search for 'def ' in the file agno/tools/grep.py",
    stream=True,
)

"""
CodingTools: Minimal Tools for Coding Agents
=============================================
A single toolkit with 4 core tools (read, edit, write, shell) that lets
an agent perform any coding task. Inspired by the Pi coding agent's
philosophy: a small number of composable tools is more powerful than
many specialized ones.

Core tools (enabled by default):
- read_file: Read files with line numbers and pagination
- edit_file: Exact text find-and-replace with diff output
- write_file: Create or overwrite files
- run_shell: Execute shell commands with timeout

Exploration tools (opt-in):
- grep: Search file contents
- find: Search for files by glob pattern
- ls: List directory contents
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.coding import CodingTools

# ---------------------------------------------------------------------------
# Create Agent with CodingTools
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[CodingTools(base_dir=".")],
    instructions="You are a coding assistant. Use the coding tools to help the user.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "List the files in the current directory and read the README.md file if it exists.",
        stream=True,
    )

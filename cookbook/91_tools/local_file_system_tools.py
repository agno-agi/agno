"""
Local File System Tools
========================

Demonstrates local file system tools for reading from and writing to files.
The agent can create files and read their contents using the local file system.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.local_file_system import LocalFileSystemTools

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Example 1: Read and write files (default)
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[LocalFileSystemTools(target_directory="output")],
    markdown=True,
)

# Example 2: Write-only mode (disable read_file)
write_only_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[LocalFileSystemTools(target_directory="output", enable_read_file=False)],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Write a file and then read it back
    agent.print_response(
        "Write a short poem about programming to a file named poem.txt, then read it back to me.",
        stream=True,
    )

    # Write-only agent: generate code and save it to disk
    # write_only_agent.print_response(
    #     "Write a Python function that calculates fibonacci numbers and save it to output/fib.py",
    #     stream=True,
    # )

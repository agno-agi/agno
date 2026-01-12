"""
FileSystemKnowledge Example
===========================
Demonstrates using FileSystemKnowledge to let an agent search local files.

Run: `python cookbook/08_knowledge/protocol/file_system.py`
"""

from agno.agent import Agent
from agno.knowledge.filesystem import FileSystemKnowledge
from agno.models.openai import OpenAIChat

# Create a filesystem knowledge base pointing to the agno library source
fs_knowledge = FileSystemKnowledge(
    base_dir="libs/agno/agno",
    include_patterns=["*.py"],
    exclude_patterns=[".git", "__pycache__", ".venv"],
)

# Base instructions for all agents
base_instructions = (
    "You are a code assistant that helps users explore the agno codebase."
)

if __name__ == "__main__":
    # ==========================================
    # Example 1: GREP mode - Search file contents
    # ==========================================
    print("\n" + "=" * 60)
    print("GREP MODE: Searching for pattern in file contents")
    print("=" * 60 + "\n")

    grep_agent = Agent(
        model=OpenAIChat(id="gpt-5.2"),
        knowledge=fs_knowledge,
        search_knowledge=True,
        instructions=f"""{base_instructions}

When searching, prefix your query with "grep:" to search for patterns in file contents.
Example: grep:def handle_tool
""",
        markdown=True,
    )

    grep_agent.print_response(
        "Find where handle_tool is defined in the codebase",
        stream=True,
    )

    # ==========================================
    # Example 2: LIST_FILES mode - List files
    # ==========================================
    print("\n" + "=" * 60)
    print("LIST_FILES MODE: Listing files matching a pattern")
    print("=" * 60 + "\n")

    list_agent = Agent(
        model=OpenAIChat(id="gpt-5.2"),
        knowledge=fs_knowledge,
        search_knowledge=True,
        instructions=f"""{base_instructions}

When searching, prefix your query with "list:" to list files matching a glob pattern.
Example: list:*.py or list:tools/*.py
""",
        markdown=True,
    )

    list_agent.print_response(
        "What Python files exist in the tools directory?",
        stream=True,
    )

    # ==========================================
    # Example 3: GET_FILE mode - Read full file
    # ==========================================
    print("\n" + "=" * 60)
    print("GET_FILE MODE: Reading full file contents")
    print("=" * 60 + "\n")

    file_agent = Agent(
        model=OpenAIChat(id="gpt-5.2"),
        knowledge=fs_knowledge,
        search_knowledge=True,
        instructions=f"""{base_instructions}

When searching, prefix your query with "file:" to get the full contents of a specific file.
Example: file:knowledge/protocol.py
""",
        markdown=True,
    )

    file_agent.print_response(
        "Read the knowledge/protocol.py file and explain what it defines",
        stream=True,
    )

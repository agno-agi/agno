"""
FileSystemKnowledge Example
===========================
Demonstrates using FileSystemKnowledge to let an agent search local files.

The FileSystemKnowledge class implements the KnowledgeProtocol and provides
three tools to the agent:
- grep_file: Search for patterns in file contents
- list_files: List files matching a glob pattern
- get_file: Read the full contents of a specific file

Run: `python cookbook/07_knowledge/protocol/file_system.py`
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

if __name__ == "__main__":
    # ==========================================
    # Single agent with all three filesystem tools
    # ==========================================
    # The agent automatically gets: grep_file, list_files, get_file
    # Plus context explaining how to use them

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        knowledge=fs_knowledge,
        search_knowledge=True,
        instructions=(
            "You are a code assistant that helps users explore the agno codebase. "
            "Use the available tools to search, list, and read files."
        ),
        markdown=True,
    )

    # Example 1: Grep - find where something is defined
    print("\n" + "=" * 60)
    print("EXAMPLE 1: Using grep_file to find code patterns")
    print("=" * 60 + "\n")

    agent.print_response(
        "Find where the KnowledgeProtocol class is defined",
        stream=True,
    )

    # Example 2: List files in a directory
    print("\n" + "=" * 60)
    print("EXAMPLE 2: Using list_files to explore directories")
    print("=" * 60 + "\n")

    agent.print_response(
        "What Python files exist in the knowledge directory?",
        stream=True,
    )

    # Example 3: Read a specific file
    print("\n" + "=" * 60)
    print("EXAMPLE 3: Using get_file to read file contents")
    print("=" * 60 + "\n")

    agent.print_response(
        "Read the knowledge/protocol.py file and explain what it defines",
        stream=True,
    )

    # ==========================================
    # Example 4: Document search (text files only)
    # ==========================================
    # Note: FileSystemKnowledge only works with text files (md, txt, etc.)
    # For PDFs, use the main Knowledge class with proper readers
    print("\n" + "=" * 60)
    print("EXAMPLE 4: Searching document files (coffee guide)")
    print("=" * 60 + "\n")

    docs_knowledge = FileSystemKnowledge(
        base_dir="cookbook/07_knowledge/testing_resources",
        include_patterns=["*.md", "*.txt"],  # Text files only, not PDFs
        exclude_patterns=[],
    )

    docs_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        knowledge=docs_knowledge,
        search_knowledge=True,
        instructions="You are a helpful assistant that answers questions from documents.",
        markdown=True,
    )

    docs_agent.print_response(
        "What knowledge do you have about coffee? Which coffee region produces Bright and nutty notes?",
        stream=True,
    )

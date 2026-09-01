"""
Multi-Workspace Example: Using tool_name_prefix for namespacing.

Demonstrates how to use multiple Workspace toolkits on the same agent
without tool name collisions. Each toolkit gets a prefix (e.g., docs_read_file,
code_read_file) so tools from different workspaces can coexist.

Use case: An agent that can access both documentation and source code,
with clear separation of which workspace each tool operates on.
"""

import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.workspace import Workspace


def main():
    # Create two temp directories to simulate docs and code workspaces
    with (
        tempfile.TemporaryDirectory() as docs_dir,
        tempfile.TemporaryDirectory() as code_dir,
    ):
        docs_path = Path(docs_dir)
        code_path = Path(code_dir)

        # Create sample files in docs workspace
        (docs_path / "getting-started.md").write_text(
            "# Getting Started\n\nWelcome to the docs!"
        )
        (docs_path / "api-reference.md").write_text(
            "# API Reference\n\n## Agent class\n..."
        )

        # Create sample files in code workspace
        (code_path / "agent.py").write_text("class Agent:\n    def run(self): pass")
        (code_path / "utils.py").write_text("def helper(): return 42")

        # Create two Workspace toolkits with different prefixes
        docs_toolkit = Workspace(
            root=docs_path,
            allowed=Workspace.READ_TOOLS,
            tool_name_prefix="docs",  # Tools: docs_read_file, docs_list_files, etc.
        )

        code_toolkit = Workspace(
            root=code_path,
            allowed=Workspace.READ_TOOLS,
            tool_name_prefix="code",  # Tools: code_read_file, code_list_files, etc.
        )

        # Verify no tool name collisions
        docs_tools = set(docs_toolkit.functions.keys())
        code_tools = set(code_toolkit.functions.keys())
        collision = docs_tools & code_tools

        print("=== Tool Registration ===")
        print(f"Docs toolkit: {sorted(docs_tools)}")
        print(f"Code toolkit: {sorted(code_tools)}")
        print(f"Collisions: {collision if collision else 'None'}")

        # Check toolkit metadata
        print(f"\n=== Toolkit Metadata ===")
        print(f"Docs toolkit name: {docs_toolkit.name}, id: {docs_toolkit.id}")
        print(f"Code toolkit name: {code_toolkit.name}, id: {code_toolkit.id}")

        # Create agent with both toolkits
        agent = Agent(
            model=OpenAIResponses(id="gpt-5.6-luna"),
            tools=[docs_toolkit, code_toolkit],
            instructions=(
                "You have access to two workspaces:\n"
                "- docs_* tools: Documentation files\n"
                "- code_* tools: Source code files\n"
                "Use the appropriate prefix based on which workspace you need."
            ),
            markdown=True,
        )

        # Check instructions include prefixed tool names
        print(f"\n=== Docs Toolkit Instructions ===")
        if docs_toolkit.instructions:
            print(docs_toolkit.instructions[:500])

        # Test the agent
        print("\n=== Agent Test ===")
        agent.print_response("List files in both workspaces")


if __name__ == "__main__":
    main()

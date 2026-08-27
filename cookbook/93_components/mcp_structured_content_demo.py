"""
MCP Structured Content Demo
===========================

Demonstrates that MCP tool results now include content in structuredContent,
fixing the issue where Claude Code would show metadata instead of the answer.

Before the fix (PR #9765), Claude Code users would see:
    {"run_id": "...", "session_id": "...", "status": "completed"}

After the fix, they see the actual answer:
    "The answer to your question is..."

Run with:
    python cookbook/93_components/mcp_structured_content_demo.py

To test with Claude Code:
    agno run cookbook/93_components/mcp_structured_content_demo.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS


def main():
    # Create an agent that will respond to queries
    agent = Agent(
        name="Helper Agent",
        id="helper-agent",
        model=OpenAIResponses(id="gpt-4o-mini"),
        instructions="You are a helpful assistant. Keep responses brief.",
    )

    # Create AgentOS with MCP enabled
    os = AgentOS(
        agents=[agent],
        mcp_server=True,  # Enable MCP with default settings
    )

    print("AgentOS with MCP server created!")
    print()
    print("The run_agent tool now returns content in structuredContent:")
    print()
    print("  result.content[0].text = 'The actual answer...'")
    print("  result.structured_content = {")
    print("      'run_id': '...',")
    print("      'session_id': '...',")
    print("      'status': 'COMPLETED',")
    print("      'content': 'The actual answer...'  # <-- NEW!")
    print("  }")
    print()
    print("This fixes Claude Code showing metadata instead of answers.")
    print()
    print("To test interactively:")
    print("  1. Run: agno run cookbook/93_components/mcp_structured_content_demo.py")
    print("  2. In Claude Code, use the run_agent tool")
    print("  3. Verify you see the agent's response, not just metadata")


if __name__ == "__main__":
    main()

"""Basic example: Using Claude Agent SDK with Agno.

This demonstrates standalone usage of ClaudeAgent — running it directly
without AgentOS.

Requirements:
    pip install claude-agent-sdk agno
    export ANTHROPIC_API_KEY=sk-...
"""

import asyncio

from agno.agent.claude import ClaudeAgent

# Create a Claude Agent with specific tools and instructions
agent = ClaudeAgent(
    agent_id="code-reviewer",
    name="Code Reviewer",
    description="Reviews code for bugs, security issues, and style improvements.",
    system_prompt="You are a code reviewer. Review code for bugs, security issues, and style. Be concise.",
    allowed_tools=["Read", "Glob", "Grep"],
    max_turns=5,
)


async def main():
    # Non-streaming usage
    print("--- Non-streaming ---")
    response = await agent.arun("What files are in the current directory?")
    print(response.content)

    # Streaming usage
    print("\n--- Streaming ---")
    async for event in agent.arun(
        "Find all Python files in the current directory", stream=True
    ):
        event_type = getattr(event, "event", "")
        if event_type == "RunContent":
            print(event.content, end="", flush=True)
        elif event_type == "ToolCallStarted":
            print(f"\n[Tool: {event.tool.tool_name}]")
        elif event_type == "RunCompleted":
            print("\n--- Done ---")


asyncio.run(main())

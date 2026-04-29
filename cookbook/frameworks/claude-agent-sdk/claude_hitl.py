"""
Claude Agent SDK with Human-in-the-Loop Confirmation (CLI)
============================================================
Demonstrates HITL tool confirmation in the terminal.

When permission_mode="default", the agent pauses before executing
write tools (Bash, Write, Edit). The user approves or denies each one.

Requirements:
    pip install claude-agent-sdk

Usage:
    python cookbook/frameworks/claude-agent-sdk/claude_hitl.py
"""

import asyncio

from agno.agents.claude import ClaudeAgent
from agno.run.agent import RunContentEvent, RunPausedEvent


async def handle_stream(agent, stream):
    """Process a stream, handling any number of HITL pauses."""
    content = ""
    async for event in stream:
        if isinstance(event, RunPausedEvent) and event.tools:
            for tool in event.tools:
                print(f"\n--- HITL PAUSE ---")
                print(f"Tool: {tool.tool_name}")
                print(f"Args: {tool.tool_args}")
                user_input = input("Allow this tool? (y/n): ").strip().lower()
                tool.confirmed = user_input in ("y", "yes", "")

            # Resume and recursively handle the continued stream
            resume_stream = agent.acontinue_run(updated_tools=event.tools, stream=True)
            content += await handle_stream(agent, resume_stream)

        elif isinstance(event, RunContentEvent) and event.content:
            content += event.content
            print(event.content, end="", flush=True)

    return content


async def main():
    agent = ClaudeAgent(
        name="Claude HITL Agent",
        model="claude-sonnet-4-20250514",
        allowed_tools=["WebSearch", "Bash", "Read"],
        permission_mode="default",
        max_turns=10,
    )

    print("Claude HITL Agent (permission_mode=default)")
    print("The agent will ask for permission before using tools.")
    print("-" * 50)

    query = "Create a file called hello.txt with the content 'Hello from HITL!' and then read it back to me"
    print(f"\nUser: {query}\n")

    response = agent.arun(input=query, stream=True)
    content = await handle_stream(agent, response)

    print(f"\n\n--- Done ({len(content)} chars) ---")


if __name__ == "__main__":
    asyncio.run(main())

"""
Claude Agent SDK with Human-in-the-Loop User Input (CLI)
=========================================================
Demonstrates HITL where the agent pauses to collect user input
before executing a tool. The user can approve, deny, or edit
the tool's arguments before it runs.

Requirements:
    pip install claude-agent-sdk

Usage:
    python cookbook/frameworks/claude-agent-sdk/claude_hitl_input.py
"""

import asyncio
import json

from agno.agents.claude import ClaudeAgent
from agno.run.agent import RunContentEvent, RunPausedEvent


async def handle_stream(agent, stream):
    """Process a stream, handling any number of HITL pauses."""
    content = ""
    async for event in stream:
        if isinstance(event, RunPausedEvent) and event.tools:
            for tool in event.tools:
                print(f"\n{'='*60}")
                print(f"HITL PAUSE — Tool: {tool.tool_name}")
                print(f"Arguments: {json.dumps(tool.tool_args, indent=2)}")
                print(f"{'='*60}")
                print("\nOptions:")
                print("  [enter] — approve as-is")
                print("  [n]     — deny this tool")
                print("  [e]     — edit arguments")
                choice = input("\nYour choice: ").strip().lower()

                if choice == "n":
                    tool.confirmed = False
                    print("Denied.")
                elif choice == "e":
                    print("\nEdit arguments (press enter to keep current value):")
                    if tool.tool_args:
                        for key, value in tool.tool_args.items():
                            new_val = input(f"  {key} [{value}]: ").strip()
                            if new_val:
                                tool.tool_args[key] = new_val
                    tool.confirmed = True
                    print(f"\nApproved with args: {json.dumps(tool.tool_args, indent=2)}")
                else:
                    tool.confirmed = True
                    print("Approved.")

            # Resume and recursively handle the continued stream
            resume_stream = agent.acontinue_run(updated_tools=event.tools, stream=True)
            content += await handle_stream(agent, resume_stream)

        elif isinstance(event, RunContentEvent) and event.content:
            content += event.content
            print(event.content, end="", flush=True)

    return content


async def main():
    agent = ClaudeAgent(
        name="Claude HITL Input Agent",
        model="claude-sonnet-4-20250514",
        allowed_tools=["Bash", "Write", "Read"],
        permission_mode="default",
        hitl_mode="user_input",  # Shows editable input fields
        max_turns=10,
    )

    print("Claude HITL Agent — User Input Mode")
    print("When the agent wants to use a write tool, you can modify its arguments.")
    print("-" * 60)

    query = "Run a bash command to show the current date and time, then write it to a file called timestamp.txt"
    print(f"\nUser: {query}\n")

    response = agent.arun(input=query, stream=True)
    content = await handle_stream(agent, response)

    print(f"\n\n--- Done ({len(content)} chars) ---")


if __name__ == "__main__":
    asyncio.run(main())

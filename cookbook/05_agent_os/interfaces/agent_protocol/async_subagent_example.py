"""
Async SubAgent Example
======================

End-to-end example: deepagents AsyncSubAgent connecting to an AgentOS
server running the Agent Protocol interface.

Prerequisites:
1. Start the Agent Protocol server:
   python cookbook/05_agent_os/interfaces/agent_protocol/server.py

   The server will run on http://localhost:7778

2. Install deepagents:
   pip install deepagents

3. Set your ANTHROPIC_API_KEY environment variable:
   export ANTHROPIC_API_KEY=your_key_here
"""

import asyncio
import uuid

from deepagents import AsyncSubAgent, create_deep_agent
from langgraph.checkpoint.memory import MemorySaver

# ---------------------------------------------------------------------------
# Create a Deep Agent with AsyncSubAgents
# ---------------------------------------------------------------------------

# MemorySaver persists conversation state (including async task tracking)
# across turns so the supervisor remembers launched tasks.
checkpointer = MemorySaver()

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    checkpointer=checkpointer,
    subagents=[
        AsyncSubAgent(
            name="researcher",
            description="Performs deep research on a topic. Use this for in-depth analysis and investigation.",
            url="http://localhost:7778/ap",
            graph_id="research_agent",
        ),
        AsyncSubAgent(
            name="assistant",
            description="A helpful assistant for quick questions and concise answers.",
            url="http://localhost:7778/ap",
            graph_id="assistant_agent",
        ),
    ],
)


# ---------------------------------------------------------------------------
# Interactive Chat
# ---------------------------------------------------------------------------


async def main():
    """Interactive chat loop with async subagent delegation."""
    print("=" * 60)
    print("Deep Agent with Async SubAgents")
    print("=" * 60)
    print()
    print("Chat with a supervisor that delegates to remote Agno agents.")
    print("Try: 'Research quantum computing' then 'Check the task'")
    print("Type 'quit' to exit.")
    print()

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input or user_input.lower() in ("quit", "exit", "q"):
            break

        response = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_input}]},
            config=config,
        )

        # Print assistant messages
        for msg in response.get("messages", []):
            content = getattr(msg, "content", None) or (
                msg.get("content") if isinstance(msg, dict) else None
            )
            role = getattr(msg, "type", None) or (
                msg.get("role") if isinstance(msg, dict) else None
            )
            if role == "ai" and content and isinstance(content, str):
                print(f"\nA: {content}\n")


if __name__ == "__main__":
    asyncio.run(main())

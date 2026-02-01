"""
Basic CLI Example - Clawdbot Clone

Run a simple interactive CLI session with your personal AI assistant.

Usage:
    .venvs/demo/bin/python cookbook/clawdbot_clone/examples/01_basic_cli.py
"""

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from cookbook.clawdbot_clone import quick_start

# Create a simple clawdbot with SQLite (easy local setup)
agent = quick_start(
    name="Jarvis",
    model="claude-sonnet-4-20250514",
    use_sqlite=True,
)

# Interactive session
print("=" * 50)
print("Clawdbot Clone - Basic CLI Example")
print("=" * 50)
print()
print("Type your message and press Enter.")
print("Type 'quit' to exit, 'memories' to see stored memories.")
print()

user_id = "demo_user"
session_id = "demo_session"

while True:
    try:
        user_input = input("You: ").strip()

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "bye"):
            print("\nJarvis: Goodbye! Talk to you later.")
            break

        if user_input.lower() == "memories":
            memories = agent.get_user_memories(user_id=user_id)
            if memories:
                print("\nStored memories:")
                for i, m in enumerate(memories, 1):
                    print(f"  {i}. {m.memory}")
            else:
                print("\nNo memories stored yet.")
            print()
            continue

        # Get response
        response = agent.run(
            input=user_input,
            user_id=user_id,
            session_id=session_id,
        )

        print(f"\nJarvis: {response.content}\n")

    except KeyboardInterrupt:
        print("\n\nInterrupted. Goodbye!")
        break

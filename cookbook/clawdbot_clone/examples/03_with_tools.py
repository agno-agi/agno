"""
Computer Control Example - Clawdbot Clone

Demonstrates the agent's ability to execute shell commands,
read/write files, run Python code, and search the web.

Usage:
    .venvs/demo/bin/python cookbook/clawdbot_clone/examples/03_with_tools.py

WARNING: This example enables shell and Python execution.
The agent will ask for confirmation before running commands.
"""

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from cookbook.clawdbot_clone import ClawdbotConfig, create_clawdbot

# Create configuration with all tools enabled
config = ClawdbotConfig(
    bot_name="Jarvis",
    bot_personality="a capable technical assistant who can control the computer",
    use_sqlite=True,
    sqlite_path="tmp/clawdbot_tools.db",
    # Enable all tools
    enable_shell=True,
    enable_file_access=True,
    enable_python=True,
    enable_web_search=True,
    enable_web_browser=True,
    # Base directory for file operations (restricts access)
    base_directory="./tmp/clawdbot_workspace",
    # Safety settings
    require_confirmation_for_shell=False,  # Set to True in production!
    require_confirmation_for_file_write=False,  # Set to True in production!
)

# Create workspace directory
workspace = Path(config.base_directory)
workspace.mkdir(parents=True, exist_ok=True)

# Create the agent
agent = create_clawdbot(config)

print("=" * 60)
print("Clawdbot Clone - Computer Control Demo")
print("=" * 60)
print()
print(f"Workspace: {workspace.absolute()}")
print()
print("Try these commands:")
print("  - 'List the files in the current directory'")
print("  - 'Create a file called hello.txt with a greeting'")
print("  - 'What is the current date and time?'")
print("  - 'Calculate the factorial of 10 using Python'")
print("  - 'Search the web for the latest AI news'")
print()
print("Type 'quit' to exit.")
print()

user_id = "demo_user"
session_id = "tools_demo"

while True:
    try:
        user_input = input("You: ").strip()

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit"):
            print("\nGoodbye!")
            break

        # Get response with streaming for long operations
        print(f"\nJarvis: ", end="", flush=True)

        response = agent.run(
            input=user_input,
            user_id=user_id,
            session_id=session_id,
        )

        print(response.content)
        print()

    except KeyboardInterrupt:
        print("\n\nInterrupted. Goodbye!")
        break

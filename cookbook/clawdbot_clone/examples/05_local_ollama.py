"""
Local/Private Mode Example - Clawdbot Clone with Ollama

Run your personal AI assistant entirely locally using Ollama.
No data leaves your machine!

Prerequisites:
    1. Install Ollama: https://ollama.ai
    2. Pull a model: ollama pull llama3.2
    3. Run this script

Usage:
    .venvs/demo/bin/python cookbook/clawdbot_clone/examples/05_local_ollama.py
"""

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from cookbook.clawdbot_clone import ClawdbotConfig, create_clawdbot

# Create configuration for local Ollama
config = ClawdbotConfig(
    bot_name="LocalJarvis",
    bot_personality="a helpful assistant running entirely on your local machine",
    # Use Ollama for local inference
    model_provider="ollama",
    model_id="llama3.2",  # or "mistral", "codellama", etc.
    ollama_host="http://localhost:11434",  # Default Ollama host
    # Use SQLite for local storage
    use_sqlite=True,
    sqlite_path="tmp/clawdbot_local.db",
    # Enable tools (all run locally)
    enable_shell=True,
    enable_file_access=True,
    enable_python=True,
    enable_web_search=False,  # Disable for fully offline mode
    enable_web_browser=False,
)

print("=" * 60)
print("Clawdbot Clone - Local/Private Mode with Ollama")
print("=" * 60)
print()
print(f"Model: {config.model_id}")
print(f"Host: {config.ollama_host}")
print()
print("All processing happens locally on your machine.")
print("No data is sent to external servers.")
print()

try:
    # Create the agent
    agent = create_clawdbot(config)

    user_id = "local_user"
    session_id = "local_session"

    print("Type your message and press Enter.")
    print("Type 'quit' to exit.")
    print()

    while True:
        try:
            user_input = input("You: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit"):
                print("\nGoodbye!")
                break

            response = agent.run(
                input=user_input,
                user_id=user_id,
                session_id=session_id,
            )

            print(f"\nLocalJarvis: {response.content}\n")

        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break

except Exception as e:
    print(f"Error: {e}")
    print()
    print("Make sure Ollama is running:")
    print("  1. Install Ollama from https://ollama.ai")
    print("  2. Run: ollama serve")
    print("  3. Pull a model: ollama pull llama3.2")
    print("  4. Try again")

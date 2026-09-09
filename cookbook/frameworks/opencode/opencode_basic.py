"""
Standalone usage of OpenCode with Agno's .run() and .print_response() methods.

OpenCode (https://opencode.ai) is an open-source coding agent that runs as a
headless HTTP server. The OpenCodeAgent adapter talks to that server, so tool
execution (file edits, shell, search) happens inside OpenCode, in the
directory the server was started in.

Requirements:
    # Install the OpenCode CLI
    npm install -g opencode-ai

    # Start the server (in the project you want the agent to work on)
    opencode serve --port 4096

Usage:
    .venvs/demo/bin/python cookbook/frameworks/opencode/opencode_basic.py
"""

from agno.agents.opencode import OpenCodeAgent

# ----- Wrap a running OpenCode server for Agno -----
agent = OpenCodeAgent(
    name="OpenCode Assistant",
    base_url="http://127.0.0.1:4096",
    # Optional: pin a model as "provider/model"; defaults to the server's default
    # model="anthropic/claude-sonnet-4-5",
)

# Use .print_response() just like a native Agno agent
agent.print_response(
    "List the files in the current directory and summarize what this project is.",
    stream=True,
)

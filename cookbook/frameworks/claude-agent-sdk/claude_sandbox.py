"""
Claude Agent SDK with Sandbox
==============================
Runs a Claude agent inside an OS-level sandbox that restricts filesystem
and network access. Useful for:

- Running agents with untrusted user input
- Code execution agents that write and run code
- Production deployments where you want defense-in-depth

The sandbox uses Apple's sandbox-exec (macOS) or landlock (Linux) to
enforce hard OS-level boundaries that the LLM cannot bypass.

Requirements:
    pip install claude-agent-sdk

Usage:
    python cookbook/frameworks/claude-agent-sdk/claude_sandbox.py

What to expect:
    - Test 1: bash cat of file inside workspace — WORKS
    - Test 2: bash cat of /etc/passwd — BLOCKED by sandbox (OS kernel denies access)
    - Test 3: write + run Python code inside workspace — WORKS
    - Test 4: bash curl to external URL — BLOCKED by sandbox (network restricted)

Note: The sandbox only restricts BASH commands. The built-in Read/Write tools
operate outside the sandbox. To restrict those, use permission rules instead.
"""

import os

from agno.agents.claude import ClaudeAgent

# Create a workspace directory for the sandboxed agent
workspace = os.path.join(os.getcwd(), "tmp", "sandbox_workspace")
os.makedirs(workspace, exist_ok=True)

# Write a test file the agent CAN read
with open(os.path.join(workspace, "hello.txt"), "w") as f:
    f.write("Hello from inside the sandbox! This file is readable.")

# ----- Sandboxed Claude Agent -----
agent = ClaudeAgent(
    name="Sandboxed Agent",
    description="A Claude agent running inside an OS-level sandbox",
    model="claude-sonnet-4-20250514",
    allowed_tools=["Bash", "Write"],
    permission_mode="acceptEdits",
    max_turns=10,
    cwd=workspace,
    sandbox={
        "enabled": True,
        "autoAllowBashIfSandboxed": True,
        "allowUnsandboxedCommands": False,  # Prevent dangerouslyDisableSandbox bypass
    },
)

print("=" * 60)
print("Test 1: Read a file INSIDE the workspace via bash (should work)")
print("=" * 60)
agent.print_response(
    f"Use bash to cat the file at {workspace}/hello.txt and tell me what it says.",
    stream=True,
)

print("\n" + "=" * 60)
print("Test 2: Write and execute code inside sandbox (should work)")
print("=" * 60)
agent.print_response(
    "Write a Python script that prints 'Hello from sandbox!' to a file called output.txt, then run it with bash and show the output.",
    stream=True,
)

print("\n" + "=" * 60)
print("Test 3: Try to run a bash command that accesses the network (should FAIL)")
print("  The sandbox restricts network access from bash commands.")
print("=" * 60)
agent.print_response(
    "Use bash to run: curl -s https://httpbin.org/get. Show the output or error.",
    stream=True,
)

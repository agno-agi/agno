"""
Agent with Superserve tools

This example shows how to use Agno's Superserve integration to run agent-generated
code in an isolated cloud sandbox (Firecracker microVM).

1. Get your Superserve API key: https://superserve.ai
2. Set the API key as an environment variable:
    export SUPERSERVE_API_KEY=ss_live_...
3. Install the dependencies:
    uv pip install agno openai superserve

The sandbox persists across tool calls, so files written and packages installed
remain available within a run (and across runs when persistent=True).
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.superserve import SuperserveTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# A focused default tool set is enabled. Every tool has its own enable_* flag, so
# you can toggle tools individually or turn everything on with all=True:
#   SuperserveTools(enable_pause_sandbox=True, enable_resume_sandbox=True)
#   SuperserveTools(enable_attach_secret=True, enable_detach_secret=True)
#   SuperserveTools(all=True)  # register every tool
# Sandboxes default to a Python-ready template; override it for other runtimes:
#   SuperserveTools(template="superserve/node-22")
# To bind a team secret to the sandbox without exposing the real credential:
#   SuperserveTools(secrets={"OPENAI_API_KEY": "openai-prod"})

agent = Agent(
    name="Coding Agent with Superserve tools",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[SuperserveTools(timeout=600)],
    markdown=True,
    instructions=[
        "You are an expert at writing and executing code in a secure Superserve sandbox.",
        "Your primary purpose is to:",
        "1. Write clear, efficient code based on user requests",
        "2. ALWAYS execute the code in the sandbox using run_python_code or run_command",
        "3. Show the actual execution results to the user",
        "4. Provide explanations of how the code works and what the output means",
        "Guidelines:",
        "- NEVER just provide code without executing it",
        "- Install missing packages when needed using run_command, for example pip install <package>",
        "- Use file operations (create_file, read_file, list_files) when working with scripts",
        "- Always show both the code AND the execution output",
        "- Handle errors gracefully and explain any issues encountered",
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Write Python code to generate the first 10 Fibonacci numbers and calculate their sum and average"
    )

"""
Agent with Upstash Box tools

This example shows how to use Agno's Upstash Box integration to run agent-generated
code in an isolated cloud Linux environment.

1. Get your Upstash Box API key from the Upstash Console: https://console.upstash.com
2. Set the API key as an environment variable:
    export UPSTASH_BOX_API_KEY=box_...
3. Install the dependencies:
    uv pip install agno openai upstash-box

The box persists across tool calls, so files written and packages installed remain
available within a run (and across runs when persistent=True). It pauses when idle
and resumes automatically on the next tool call.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.upstash_box import UpstashBoxTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# A focused default tool set is enabled. Every tool has its own enable_* flag, so
# you can toggle tools individually or turn everything on with all=True:
#   UpstashBoxTools(enable_pause_box=True, enable_resume_box=True, enable_snapshot_box=True)
#   UpstashBoxTools(all=True)  # register every tool
# Boxes default to the Python runtime; pick another runtime or a bigger size:
#   UpstashBoxTools(runtime="node", size="medium")
# Stop long-running commands after a number of seconds (exit code 124):
#   UpstashBoxTools(command_timeout=120)
# Reuse a box you already have:
#   UpstashBoxTools(box_id="your-box-id")

agent = Agent(
    name="Coding Agent with Upstash Box tools",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[UpstashBoxTools()],
    markdown=True,
    instructions=[
        "You are an expert at writing and executing code in a secure Upstash Box.",
        "Your primary purpose is to:",
        "1. Write clear, efficient code based on user requests",
        "2. ALWAYS execute the code in the box using run_python_code or run_command",
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

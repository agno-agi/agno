"""
Agent with Daytona tools

This example shows how to use Agno's Daytona integration to run Agent-generated code in a remote, secure sandbox.

1. Get your Daytona API key and API URL: https://app.daytona.io/dashboard/keys
2. Set the API key and API URL as environment variables:
    export DAYTONA_API_KEY=<your_api_key>
    export DAYTONA_API_URL=<your_api_url> (optional)
3. Install the dependencies:
    uv pip install agno anthropic daytona
"""

from agno.agent import Agent
from agno.tools.daytona import DaytonaTools

# ---------------------------------------------------------------------------
# Example 1: Basic persistent sandbox (default behaviour)
# ---------------------------------------------------------------------------

agent = Agent(
    name="Coding Agent with Daytona tools",
    tools=[DaytonaTools()],
    markdown=True,
    instructions=[
        "You are an expert at writing and executing code. You have access to a remote, secure Daytona sandbox.",
        "Your primary purpose is to:",
        "1. Write clear, efficient code based on user requests",
        "2. ALWAYS execute the code in the Daytona sandbox using run_code",
        "3. Show the actual execution results to the user",
        "4. Provide explanations of how the code works and what the output means",
        "Guidelines:",
        "- NEVER just provide code without executing it",
        "- Execute all code using the run_code tool to show real results",
        "- Support Python, JavaScript, and TypeScript execution",
        "- Use file operations (create_file, read_file) when working with scripts",
        "- Install missing packages when needed using run_shell_command",
        "- Always show both the code AND the execution output",
        "- Handle errors gracefully and explain any issues encountered",
    ],
)

# ---------------------------------------------------------------------------
# Example 2: Ephemeral sandbox — auto-deleted once stopped
#
# Useful for one-shot tasks where you don't want sandbox state to linger.
# auto_stop_interval stops the sandbox after 30 minutes of inactivity;
# ephemeral=True ensures it is deleted immediately on stop.
# ---------------------------------------------------------------------------

ephemeral_agent = Agent(
    name="Ephemeral Coding Agent",
    tools=[
        DaytonaTools(
            ephemeral=True,
            auto_stop_interval=30,  # stop after 30 minutes of inactivity
        )
    ],
    markdown=True,
    instructions=["Execute the requested code and return the results."],
)

# ---------------------------------------------------------------------------
# Example 3: Sandbox with lifecycle management
#
# auto_delete_interval removes the sandbox after it has been stopped for
# 4 hours, preventing stale sandboxes from accumulating.
# ---------------------------------------------------------------------------

managed_agent = Agent(
    name="Managed Coding Agent",
    tools=[
        DaytonaTools(
            auto_stop_interval=60,  # stop after 1 hour idle
            auto_archive_interval=120,  # archive after 2 hours stopped
            auto_delete_interval=240,  # delete after 4 hours stopped
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Write JavaScript code to generate 10 random numbers between 1 and 100, sort them in ascending order, and print each number"
    )

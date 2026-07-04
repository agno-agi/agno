"""🧰 Agent with BoxLite tools

This example shows how to use Agno's BoxLite integration to run Agent-generated code
in a fast, local micro-VM sandbox. BoxLite boots an isolated VM from an OCI image in
sub-second time — no API key or cloud account required.

1. Install the dependencies:
    uv pip install agno anthropic boxlite
2. Run:
    python cookbook/91_tools/boxlite_tools.py
"""

from agno.agent import Agent
from agno.tools.boxlite import BoxLiteTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    name="Coding Agent with BoxLite tools",
    tools=[BoxLiteTools()],
    markdown=True,
    instructions=[
        "You are an expert at writing and executing code. You have access to a local, isolated BoxLite sandbox.",
        "Your primary purpose is to:",
        "1. Write clear, efficient code based on user requests",
        "2. ALWAYS execute the code in the BoxLite sandbox using run_code",
        "3. Show the actual execution results to the user",
        "4. Provide explanations of how the code works and what the output means",
        "Guidelines:",
        "- NEVER just provide code without executing it",
        "- Execute all code using the run_code tool to show real results",
        "- Use file operations (create_file, read_file) when working with scripts",
        "- Install missing packages when needed using run_shell_command",
        "- Always show both the code AND the execution output",
        "- Handle errors gracefully and explain any issues encountered",
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Write Python code to generate 10 random numbers between 1 and 100, sort them in ascending order, and print each number"
    )

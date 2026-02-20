"""
Level 1: Agent with Tools
======================================
The simplest useful agent. A model, tools, and clear instructions.
No memory, no persistence — pure stateless tool calling.

This is where every agent should start. You'd be surprised how much
a single agent with good instructions and the right tools can accomplish.

Run standalone:
    python cookbook/levels_of_agentic_software/level_1_tools.py

Run via Agent OS:
    python cookbook/levels_of_agentic_software/run.py
    Then visit https://os.agno.com and select "L1 Coding Agent"

Example prompt:
    "Write a Fibonacci function, save it to fib.py, and run it to verify"
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.coding import CodingTools

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a coding agent. You write clean, well-documented Python code.

## Workflow

1. Understand the task
2. Write the code and save it to a file
3. Run the file to verify it works
4. If there are errors, fix them and re-run

## Rules

- Always save code to files before running
- Include type hints on function signatures
- Add a brief docstring to each function
- Test with at least 2-3 example inputs
- No emojis\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
l1_coding_agent = Agent(
    name="L1 Coding Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=instructions,
    tools=[CodingTools(base_dir=WORKSPACE, all=True)],
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    l1_coding_agent.print_response(
        "Write a Fibonacci function that returns the nth Fibonacci number. "
        "Save it to fib.py with a main block that prints the first 10 values, "
        "then run it to verify.",
        stream=True,
    )

"""Agent with Tenki tools.

This example runs Agent-generated code in a persistent Tenki cloud sandbox.

Prerequisites:
1. Use Python 3.10 or newer.
2. Create a Tenki API key: https://tenki.cloud/docs/sandbox/sdk
3. Set the API key:
   export TENKI_API_KEY=<your_api_key>
4. Optionally select a workspace explicitly:
   export TENKI_WORKSPACE_ID=<your_workspace_id>
5. Install the dependencies:
   uv pip install "agno[tenki]" openai

The Tenki SDK determines the workspace from the API key automatically. Set TENKI_WORKSPACE_ID only when you need to
override it explicitly.
"""

from agno.agent import Agent
from agno.tools.tenki import TenkiTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    name="Coding Agent with Tenki tools",
    tools=[
        TenkiTools(
            add_instructions=True,
            sandbox_options={
                "name": "agno-tenki-example",
                "max_duration": 900,
                "metadata": {"created_by": "agno"},
            },
        )
    ],
    instructions=[
        "Write clear Python code and execute it in the Tenki sandbox.",
        "Use the file tools when the task asks you to create or inspect files.",
        "Report the actual command output and explain any errors.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Write Python code that generates the first 10 Fibonacci numbers, saves them to fibonacci.txt, "
        "then reads the file and reports the numbers and their sum.",
        stream=True,
    )

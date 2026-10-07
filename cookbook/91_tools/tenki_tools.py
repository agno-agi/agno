"""Agent with Tenki tools.

This example runs Agent-generated code in a persistent Tenki cloud sandbox.

Prerequisites:
1. Use Python 3.10 or newer.
2. Create a Tenki API key: https://tenki.cloud/docs/sandbox/sdk
3. Set the API key:
   export TENKI_API_KEY=<your_api_key>
4. Optionally select a workspace explicitly:
   export TENKI_WORKSPACE_ID=<your_workspace_id>
5. Set one model provider API key:
   # OpenAI (used by the default Agent model)
   export OPENAI_API_KEY=<your_openai_api_key>
   # Anthropic (configure model=Claude(...) on Agent)
   export ANTHROPIC_API_KEY=<your_anthropic_api_key>
   # Google Gemini (configure model=Gemini(...) on Agent)
   export GOOGLE_API_KEY=<your_google_api_key>
   # Groq (configure model=Groq(...) on Agent)
   export GROQ_API_KEY=<your_groq_api_key>
6. Install the dependencies:
   uv pip install "agno[tenki,sqlite,openai]"
   Replace openai with anthropic, google, or groq when using that provider.

The Tenki SDK determines the workspace from the API key automatically. Set TENKI_WORKSPACE_ID only when you need to
override it explicitly. The SQLite database persists the sandbox ID in Agent session state across calls that use the
same session ID. Auto-created sandboxes are bounded to 15 minutes, and the optional termination tool requires
confirmation.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.tools.tenki import TenkiTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

tenki_tools = TenkiTools(
    add_instructions=True,
    enable_terminate_sandbox=True,
    sandbox_options={
        "name": "agno-tenki-example",
        "max_duration": 900,
        "metadata": {"created_by": "agno"},
    },
)

agent = Agent(
    name="Coding Agent with Tenki tools",
    session_id="tenki-tools-demo",
    db=SqliteDb(db_file="tmp/tenki_tools.db"),
    tools=[tenki_tools],
    instructions=[
        "Write clear Python code and execute it in the Tenki sandbox.",
        "Use the file tools when the task asks you to create or inspect files.",
        "Report the actual command output and explain any errors.",
        "Keep the sandbox for follow-up calls unless the user explicitly asks you to terminate it.",
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

"""
CodeMode - Shell cells
======================

IPython's cell magics come for free, so shell orchestration costs zero extra
tool surface. Each `%%bash` cell is a throw-away subshell: `cd` and `export`
do not carry over. `%cd` and `os.environ[...]` are kernel-level and do apply
to every later cell.

Pass `allow_shell=False` to strip the magic and reject `%%bash` cells. That is
a footgun reducer, not a security boundary: CodeMode is not a sandbox.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.code import CodeMode

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
code = CodeMode()

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[code],
    instructions=[
        "Use the code environment for shell work.",
        "Report only what you learned, not raw command output.",
    ],
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        agent.print_response(
            "Using a %%bash cell, count how many Python files are in the current "
            "directory tree, then report the count and the Python version the "
            "environment is running.",
            session_id="code-mode-shell",
        )
    finally:
        code.shutdown()

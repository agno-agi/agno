"""
Shell Tools
=============================

Demonstrates shell tools.

``run_shell_command`` executes an arbitrary command on the host OS. To avoid
turning the agent into an RCE sink under prompt injection, prefer one of the
hardened configurations shown below.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.shell import ShellTools

# ---------------------------------------------------------------------------
# Create Agent
#
# Pick the hardening posture that matches your trust boundary:
#   - require_confirmation=True: gate every command behind human approval.
#   - restrict_to_base_dir=True + allowed_commands: allowlist + path containment.
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        ShellTools(
            require_confirmation=True,
            restrict_to_base_dir=True,
        )
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Show me the contents of the current directory", markdown=True)

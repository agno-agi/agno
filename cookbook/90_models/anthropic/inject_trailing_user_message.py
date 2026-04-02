"""
Anthropic Inject Trailing User Message
======================================

Some models do not support assistant message prefill — the API rejects
requests where the conversation ends with an assistant turn. Enable
`inject_trailing_user_message` to automatically append a user turn so
the request stays valid. This is needed for reasoning flows, session
history replay, or any scenario that produces trailing assistant messages.

Use `trailing_user_message_content` to customise the injected text (defaults to ".").
"""

from agno.agent import Agent
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Claude(id="claude-sonnet-4-6", inject_trailing_user_message=True),
    reasoning=True,
    markdown=True,
)

# With custom trailing content
agent_custom = Agent(
    model=Claude(
        id="claude-sonnet-4-6",
        inject_trailing_user_message=True,
        trailing_user_message_content="continue",
    ),
    reasoning=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is 15 + 27?")
    agent_custom.print_response("What is 15 + 27?")

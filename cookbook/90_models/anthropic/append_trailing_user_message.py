"""
Anthropic Append Trailing User Message
======================================

Claude 4.6+ does not support assistant message prefill. Enable
`append_trailing_user_message` to append a trailing user turn when the
conversation ends with an assistant message (e.g. during reasoning).

Use `trailing_user_message_content` to customise the appended text (defaults to "continue").

Note: Claude 4.6+ models auto-detect and enable this flag automatically.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Claude(id="claude-sonnet-4-6", append_trailing_user_message=True),
    reasoning=True,
    markdown=True,
)

# With custom trailing content
agent_custom = Agent(
    model=Claude(
        id="claude-sonnet-4-6",
        append_trailing_user_message=True,
        trailing_user_message_content=".",
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

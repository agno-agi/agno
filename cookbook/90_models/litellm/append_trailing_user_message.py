"""
LiteLLM Append Trailing User Message
=====================================

Claude 4.6+ does not support assistant message prefill. Enable
`append_trailing_user_message` to append a trailing user turn when the
conversation ends with an assistant message (e.g. during reasoning).

Use `trailing_user_message_content` to customise the appended text (defaults to "continue").

Note: Claude 4.6+ models auto-detect and enable this flag automatically.
"""

from agno.agent import Agent
from agno.models.litellm import LiteLLM

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=LiteLLM(
        id="anthropic/claude-sonnet-4-6",
        # Claude 4.6 rejects temperature + top_p together; drop top_p.
        top_p=None,
        append_trailing_user_message=True,
    ),
    reasoning=True,
    markdown=True,
)

# With custom trailing content
agent_custom = Agent(
    model=LiteLLM(
        id="anthropic/claude-sonnet-4-6",
        top_p=None,
        append_trailing_user_message=True,
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

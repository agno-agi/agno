"""
Fallback Models — Callback Notification
==========================================

Use the ``callback`` parameter on FallbackConfig to get notified
when a fallback model is activated. This is useful for metrics,
alerting, or logging which model actually served a request.

The callback fires *after* the fallback model succeeds (including
after the full stream completes for streaming calls).
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.fallback import FallbackConfig
from agno.models.openai import OpenAIChat


# ---------------------------------------------------------------------------
# Define a callback
# ---------------------------------------------------------------------------
def on_fallback(
    primary_model_id: str, fallback_model_id: str, error: Exception
) -> None:
    print(f"[fallback] {primary_model_id} -> {fallback_model_id} (reason: {error})")


# ---------------------------------------------------------------------------
# Create Agent with callback
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o", base_url="http://localhost:1/v1", retries=0),
    fallback_config=FallbackConfig(
        on_error=[Claude(id="claude-sonnet-4-20250514")],
        callback=on_fallback,
    ),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is the meaning of life?", stream=True)

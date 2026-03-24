"""
Claude Sonnet 4.6 assistant-prefill migration example.

Run:
    python cookbook/90_models/anthropic/sonnet_4_6_assistant_prefill_repro.py

What this shows:
1. The old Claude 4.5-style assistant-prefill pattern is now rejected early by Agno.
2. The Claude 4.6-safe pattern ends with a user message and succeeds.
"""

from os import getenv
from pathlib import Path

from agno.models.anthropic import Claude
from agno.models.message import Message
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")


MODEL_ID = "claude-sonnet-4-6"

SYSTEM_PROMPT = (
    "You are a customer support triage assistant. "
    "Return a compact JSON object with the keys: "
    "priority, category, customer_sentiment, and needs_human_agent."
)

USER_TICKET = (
    "Ticket ID: CS-18427\n"
    "Customer: Our production checkout is failing for multiple users after today's deploy. "
    "Payments are being authorized, but the order confirmation page crashes and no receipt is sent. "
    "This is affecting revenue and we need an urgent response.\n\n"
    "Classify this ticket and return only JSON."
)


def run_invalid_prefill_example(model: Claude) -> None:
    print("\n=== Invalid Claude 4.6 Pattern ===")
    invalid_messages = [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(role="user", content=USER_TICKET),
        Message(role="assistant", content='{"priority":'),
    ]

    try:
        model.response(messages=invalid_messages)
    except ValueError as exc:
        print(exc)


def run_valid_migrated_example(model: Claude) -> None:
    print("\n=== Valid Claude 4.6 Pattern ===")
    valid_messages = [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(
            role="user",
            content=(
                f"{USER_TICKET}\n\n"
                "Start your response directly with a JSON object. "
                'The JSON must include the keys "priority", "category", '
                '"customer_sentiment", and "needs_human_agent".'
            ),
        ),
    ]

    response = model.response(messages=valid_messages)
    print(response.content)


def main() -> None:
    if not getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY before running this example.")

    model = Claude(id=MODEL_ID, max_tokens=128)

    run_invalid_prefill_example(model)
    run_valid_migrated_example(model)


if __name__ == "__main__":
    main()

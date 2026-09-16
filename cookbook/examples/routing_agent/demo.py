"""Runnable companion to the routing agent guide."""

import httpx
from pydantic import ValidationError
from routing_schema import MessageRoute

# ---------------------------------------------------------------------------
# Create the example
# ---------------------------------------------------------------------------

QUEUES = {
    "billing": "billing-support",
    "technical": "technical-support",
    "order": "order-support",
    "other": "general-support",
}


def select_queue(message: str) -> str:
    try:
        response = httpx.post(
            "http://localhost:7777/agents/message-router/runs",
            data={"message": message, "stream": "false"},
            timeout=60,
        )
        response.raise_for_status()
        route = MessageRoute.model_validate(response.json()["content"], strict=True)
    except (httpx.HTTPError, ValidationError, ValueError, KeyError, TypeError):
        return "manual-review"

    if route.needs_review:
        return "manual-review"
    if route.priority == "urgent":
        return "priority-support"
    return QUEUES[route.category]


# ---------------------------------------------------------------------------
# Run the example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    queue = select_queue(
        "I was charged twice for order ORD-1042. Can you refund the duplicate charge?"
    )
    print(queue)

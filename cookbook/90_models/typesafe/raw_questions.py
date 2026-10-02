"""
Jev Raw Questions
=================

Evaluate a refund request against a supplied policy using Noul, Choice, and Score.
The run content contains decision values; provider metadata contains the full
answers and probabilities. Thresholds determine a policy decision in code.
This example only displays the decision; it does not issue a refund.

Requires Python 3.10+, typesafe-sdk, and TYPESAFE_API_KEY.
"""

import json

from rich.pretty import pprint

from agno.agent import Agent
from agno.models.typesafe import Jev
from agno.run.base import RunStatus

questions = {
    "refund_requested": {
        "type": "noul",
        "instructions": "Does the customer ask for their money back in state.input?",
    },
    "policy_allows_refund": {
        "type": "noul",
        "instructions": "Does the supplied refund policy allow the refund requested in state.input?",
        "criteria": {
            "true": "The policy clearly covers this situation.",
            "false": "The policy excludes this situation or does not mention it.",
        },
    },
    "next_step": {
        "type": "choice",
        "instructions": "What should happen next with the message in state.input under the supplied policy?",
        "criteria": {
            "refund": "Issue a refund",
            "replace": "Send a replacement",
            "ask_for_details": "More information is needed before acting",
            "none": "No action is needed",
        },
    },
    "effort": {
        "type": "score",
        "instructions": "How much work will it take to resolve the message in state.input?",
        "criteria": [
            "A single standard action",
            "Some judgment or a few steps",
            "An unusual case that needs escalation",
        ],
    },
}

agent = Agent(
    model=Jev(questions=questions),
    cache_session=True,
    instructions="Refund policy: duplicate charges are refunded in full. Change-of-mind returns are not refunded after 30 days.",
)

if __name__ == "__main__":
    agent.print_response(
        "I was charged twice for order A-104. Please refund the duplicate charge."
    )
    response = agent.get_last_run_output()
    if response is not None and response.status == RunStatus.completed:
        values = json.loads(response.content)
        decision = (
            "refund_eligible"
            if values["refund_requested"] >= 0.8
            and values["policy_allows_refund"] >= 0.8
            else "human_review"
        )
        pprint({"policy_decision": decision})
        pprint(response.model_provider_data)

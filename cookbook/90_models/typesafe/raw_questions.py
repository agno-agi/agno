"""
Jev Raw Questions
=================

Demonstrates asking Jev raw System One questions with `Jev(questions=...)`.

Use this when you want the full answers - every probability, not just the winning value -
or when a question needs structured instructions. The run content is the answers as JSON.

The three question types:
- noul:   a yes/no question; the answer is the probability of yes
- choice: pick one option; `criteria` maps each option to a description (or None)
- score:  rate along ordered levels; `criteria` lists the levels, lowest first

The agent's instructions reach Jev as `context`, so a question can point at them.

Requirements:
- `pip install typesafe-sdk` (Python 3.10+)
- export TYPESAFE_API_KEY="your_api_key"
"""

import json

from agno.agent import Agent
from agno.models.typesafe import Jev

# ---------------------------------------------------------------------------
# Define the Questions
# ---------------------------------------------------------------------------

questions = {
    "refund_requested": {
        "type": "noul",
        "instructions": "Does the customer ask for their money back in `request`?",
    },
    "policy_allows_refund": {
        "type": "noul",
        "instructions": "Does the refund policy in `context` allow the refund asked for in `request`?",
        "criteria": {
            "true": "The policy clearly covers this situation.",
            "false": "The policy excludes this situation or does not mention it.",
        },
    },
    "next_step": {
        "type": "choice",
        "instructions": "What should happen next with this message?",
        "criteria": {
            "refund": "Issue a refund",
            "replace": "Send a replacement",
            "ask_for_details": "More information is needed before acting",
            "none": "No action is needed",
        },
    },
    "effort": {
        "type": "score",
        "instructions": "How much work will it take to resolve this message?",
        "criteria": [
            "A single standard action",
            "Some judgment or a few steps",
            "An unusual case that needs escalation",
        ],
    },
}

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Jev(questions=questions),
    instructions="Refund policy: duplicate charges are refunded in full. Change-of-mind returns are not refunded after 30 days.",
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run = agent.run(
        "I was charged twice for order A-104. Please refund the duplicate charge."
    )
    answers = json.loads(run.content)

    print("refund requested:    ", answers["refund_requested"]["noul"])
    print("policy allows refund:", answers["policy_allows_refund"]["noul"])
    print(
        "next step:           ",
        answers["next_step"]["choice"],
        answers["next_step"]["probabilities"],
    )
    print(
        "effort:              ",
        answers["effort"]["score"],
        "confidence",
        answers["effort"]["confidence"],
    )

    # Thresholds and policy live in code, not in the model
    if (
        answers["refund_requested"]["noul"] > 0.8
        and answers["policy_allows_refund"]["noul"] > 0.8
    ):
        print("\nDecision: refund automatically")
    else:
        print("\nDecision: send to a person")

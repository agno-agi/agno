"""Evaluate a support agent against reference answers using Jev.

Requires Python 3.10+, typesafe-sdk, openai, TYPESAFE_API_KEY, and OPENAI_API_KEY.
Each case generates one answer, then the suite calls the shared scorer's ascore.
The renderer shows each probability and threshold decision after the response,
and includes a Score column in the summary.

python cookbook/09_evals/accuracy/jev_accuracy_suite.py
python cookbook/09_evals/accuracy/jev_accuracy_suite.py --list
python cookbook/09_evals/accuracy/jev_accuracy_suite.py --tag smoke
python cookbook/09_evals/accuracy/jev_accuracy_suite.py --json-output tmp/jev-evals.json

The CLI exits nonzero on failures. Case pass counts are distinct from the
individual correctness probabilities. Calibrate the 0.8 threshold on your data.
"""

import sys

from agno.agent import Agent
from agno.eval import Case, cli
from agno.models.openai import OpenAIResponses
from agno.scorer.typesafe import JevAccuracyScorer

agent = Agent(
    id="support-policy-agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions=(
        "Answer support questions briefly using this policy: refunds must be requested "
        "within 30 days of purchase and require a receipt. Duplicate charges are refunded "
        "in full. Do not claim to have processed refunds."
    ),
)
scorer = JevAccuracyScorer(pass_threshold=0.75)
CASES = (
    Case(
        name="refund_requirements",
        agent=agent,
        input="What are the requirements for a refund?",
        expected="Request a refund within 30 days of purchase and provide the receipt.",
        scorer=scorer,
        tags=("smoke", "refunds"),
    ),
    Case(
        name="late_refund",
        agent=agent,
        input="I bought this 45 days ago. Is it within the refund window?",
        expected="No. The refund window is 30 days from purchase.",
        scorer=scorer,
        tags=("refunds",),
    ),
    Case(
        name="duplicate_charge",
        agent=agent,
        input="Your system charged me twice. What is the policy for the duplicate charge?",
        expected="Duplicate charges are refunded in full.",
        scorer=scorer,
        tags=("smoke", "billing"),
    ),
)

if __name__ == "__main__":
    sys.exit(cli(CASES))
